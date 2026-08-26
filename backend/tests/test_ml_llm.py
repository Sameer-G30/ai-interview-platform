"""Unit tests for `ml.llm`: schema enforcement, backend selection, rubrics, skippable live Ollama.

These do not need live Postgres/Redis (unlike the job/resume/posting tests). HTTP backends are
exercised with `httpx.MockTransport` so CI/offline stays green. The one live-Ollama smoke test
skips (never fails) when the daemon is down or has no models pulled, matching the MiniLM smoke
pattern in `test_ml_matching.py`.
"""

from __future__ import annotations  # forward refs in FakeBackend without quotes

import json  # build mock assistant payloads and inspect request bodies
from dataclasses import replace  # swap ollama_model on LLMConfig for the live smoke fallback
from types import SimpleNamespace  # duck-typed Settings for config_from_settings

import httpx  # MockTransport + a 2s tags probe for the live smoke
import pytest  # skip / raises
from ml.llm import (
    AnswerEvaluation,  # 0-5 judge schema
    LLMConfig,  # factory input
    LLMJSONError,  # invalid JSON
    LLMProvider,  # facade
    LLMProviderError,  # HTTP failures
    LLMSchemaError,  # JSON that fails Pydantic
    OllamaBackend,  # LLM_PROVIDER=ollama
    OpenAICompatBackend,  # LLM_PROVIDER=openai_compat
    RubricNotFoundError,  # missing rubric file
    config_from_settings,  # Settings -> LLMConfig
    evaluate_answer,  # module-level entry point
    get_provider,  # factory
    list_rubrics,  # discover shipped files
    load_rubric,  # read one rubric body
    parse_structured,  # JSON + schema helper
)
from pydantic import BaseModel, Field  # a tiny extra schema so complete_json is not AnswerEvaluation-only

from app.core.config import Settings  # confirm LLM_* fields are wired without constructing a provider

# A known-good judge payload used by fake backends and MockTransport handlers.
_VALID_EVALUATION = {  # matches AnswerEvaluation: score 0-5, non-empty rationale, two lists
    "score": 4,  # in-range integer
    "rationale": "Covers the core idea with a clear definition.",  # min_length=1
    "strengths": ["correct definition"],  # required list
    "improvements": ["add a concrete example"],  # required list
}


class FakeBackend:
    """Test double: returns a canned string from `generate` and records the messages it was given."""

    name = "fake"  # not a real LLM_PROVIDER value; only injected via get_provider(backend=...)

    def __init__(self, text: str) -> None:  # text is the raw assistant body complete_json will parse
        self.text = text  # returned verbatim from generate()
        self.last_messages: list[dict[str, str]] | None = None  # captured for rubric/schema-contract assertions
        self.last_schema: dict | None = None  # captured so tests can see JSON Schema was forwarded

    def generate(
        self,
        messages: list[dict[str, str]],  # includes the prepended JSON-contract system turn
        *,
        temperature: float = 0.0,  # unused; kept for LLMBackend parity
        json_schema: dict | None = None,  # forwarded from complete_json
    ) -> str:
        del temperature  # fake is deterministic; temperature is a production-backend concern
        self.last_messages = messages  # complete_json prepends the schema contract before this is called
        self.last_schema = json_schema  # Ollama would send this as `format`; we just record it
        return self.text  # may be valid JSON, prose, or out-of-range JSON depending on the test

    def close(self) -> None:
        return None  # nothing to close; production backends close an owned httpx.Client


class TinySchema(BaseModel):
    """Minimal extra model so tests prove complete_json is not hard-coded to AnswerEvaluation."""

    ok: bool = Field(description="Whether the dummy check passed.")  # required boolean


def test_parse_structured_accepts_valid_evaluation() -> None:
    """Happy path: strict JSON that matches AnswerEvaluation becomes a typed object."""
    parsed = parse_structured(json.dumps(_VALID_EVALUATION), AnswerEvaluation)  # dumps so this is a JSON string
    assert parsed.score == 4  # in-range
    assert parsed.rationale.startswith("Covers")  # required justification survived
    assert parsed.strengths == ["correct definition"]  # list field
    assert parsed.improvements == ["add a concrete example"]  # list field


def test_parse_structured_rejects_prose_as_json_error() -> None:
    """Free text is a typed JSON error, not a string the caller is expected to scrape."""
    with pytest.raises(LLMJSONError, match="valid JSON") as caught:  # not LLMSchemaError
        parse_structured("The candidate did well and I would give them a 4.", AnswerEvaluation)
    assert "candidate did well" in caught.value.raw_text  # truncated dump is on the exception


def test_parse_structured_rejects_markdown_fences_as_json_error() -> None:
    """We do not strip ```json fences and hope — that would be the silent prose fallback the plan forbids."""
    fenced = "```json\n" + json.dumps(_VALID_EVALUATION) + "\n```"  # common model wrapping
    with pytest.raises(LLMJSONError, match="valid JSON"):  # still invalid JSON as a whole document
        parse_structured(fenced, AnswerEvaluation)


def test_parse_structured_rejects_out_of_range_score_as_schema_error() -> None:
    """A JSON object with score=7 is valid JSON and a schema failure, not a value to clamp to 5."""
    bad = {**_VALID_EVALUATION, "score": 7}  # 7 is outside ge=0, le=5
    with pytest.raises(LLMSchemaError, match="AnswerEvaluation"):  # Pydantic ValidationError wrapped
        parse_structured(json.dumps(bad), AnswerEvaluation)


def test_parse_structured_rejects_missing_rationale_as_schema_error() -> None:
    """Missing required fields fail the schema even when the rest of the JSON is well-typed."""
    bad = {"score": 3, "strengths": [], "improvements": []}  # rationale omitted
    with pytest.raises(LLMSchemaError, match="AnswerEvaluation"):  # not a defaulted empty rationale
        parse_structured(json.dumps(bad), AnswerEvaluation)


def test_complete_json_is_generic_over_the_response_model() -> None:
    """The same provider path validates whatever Pydantic model the caller passed, not only AnswerEvaluation."""
    backend = FakeBackend('{"ok": true}')  # TinySchema JSON
    provider = LLMProvider(backend)  # skip the factory; we are testing complete_json itself
    parsed = provider.complete_json([{"role": "user", "content": "ping"}], TinySchema)  # generic path
    assert parsed.ok is True  # coerced from JSON true
    assert backend.last_schema is not None  # JSON Schema was forwarded to the backend
    assert "ok" in backend.last_schema.get("properties", {})  # schema is TinySchema's, not AnswerEvaluation


def test_complete_json_does_not_fall_back_when_json_is_invalid() -> None:
    """If the model rambles, complete_json raises LLMJSONError instead of returning the prose."""
    provider = LLMProvider(FakeBackend("sure, here are some thoughts about the answer"))  # not JSON
    with pytest.raises(LLMJSONError):  # typed; callers can retry or mark the job failed
        provider.complete_json([{"role": "user", "content": "score this"}], AnswerEvaluation)


def test_get_provider_selects_ollama_and_openai_compat() -> None:
    """Factory returns the matching backend class; unknown names raise ValueError like get_backend()."""
    ollama = get_provider(LLMConfig(provider="ollama"))  # default product path
    assert ollama.name == "ollama"  # facade exposes the selector
    assert isinstance(ollama.backend, OllamaBackend)  # HTTP adapter, not constructed with an open client
    openai = get_provider(LLMConfig(provider="openai_compat"))  # hosted path
    assert openai.name == "openai_compat"  # selector string matches .env.example
    assert isinstance(openai.backend, OpenAICompatBackend)  # other HTTP adapter
    with pytest.raises(ValueError, match="unknown LLM provider"):  # not silently aliased to ollama
        get_provider(LLMConfig(provider="claude"))  # a third name is a caller bug


def test_get_provider_does_not_open_http_client_until_generate() -> None:
    """Lazy client: constructing the provider (and importing FastAPI) must not talk to Ollama."""
    provider = get_provider(LLMConfig(provider="ollama"))  # same call Phase 9 will make in the worker
    assert provider.backend._owned_client is None  # owned httpx.Client is created on first generate()
    assert provider.backend._injected_client is None  # production path does not inject a client
    provider.close()  # close() is safe when nothing was opened


def test_settings_exposes_llm_provider_fields() -> None:
    """LLM_* from .env.example is wired into Settings this phase, not a parallel YAML/DB config scheme."""
    fields = Settings.model_fields  # class-level; does not construct a provider or open HTTP
    for name in (
        "llm_provider",  # LLM_PROVIDER
        "ollama_base_url",  # OLLAMA_BASE_URL
        "ollama_model",  # OLLAMA_MODEL
        "openai_compat_base_url",  # OPENAI_COMPAT_BASE_URL
        "openai_compat_api_key",  # OPENAI_COMPAT_API_KEY
        "openai_compat_model",  # OPENAI_COMPAT_MODEL
    ):
        assert name in fields  # pydantic-settings maps the env names automatically


def test_config_from_settings_maps_duck_typed_attributes() -> None:
    """Phase 9 will pass get_settings(); tests pass a SimpleNamespace so this module does not need FastAPI."""
    settings = SimpleNamespace(  # duck-typed; no pydantic-settings involved
        llm_provider="openai_compat",  # selector
        ollama_base_url="http://localhost:11434/",  # trailing slash is stripped
        ollama_model="llama3.2:latest",  # unused when provider is openai_compat, still mapped
        openai_compat_base_url="https://api.example.com/v1/",  # trailing slash stripped
        openai_compat_api_key="sk-test",  # Bearer token
        openai_compat_model="gpt-4o-mini",  # remote id
    )
    config = config_from_settings(settings)  # the helper Phase 9 should use
    assert config.provider == "openai_compat"  # lowercased strip happens in get_provider too
    assert config.ollama_base_url == "http://localhost:11434"  # slash gone
    assert config.openai_compat_base_url == "https://api.example.com/v1"  # slash gone
    assert config.openai_compat_api_key == "sk-test"  # key preserved


def test_load_rubric_ships_technical_and_behavioral_v1() -> None:
    """Versioned files exist under ml/llm/rubrics/; bumping them is a new file, not a backend edit."""
    shipped = set(list_rubrics())  # (name, version) pairs
    assert ("technical_answer", 1) in shipped  # 0-5 technical rubric
    assert ("behavioral_answer", 1) in shipped  # 0-5 behavioral rubric
    technical = load_rubric("technical_answer", 1)  # body used as a system prompt
    behavioral = load_rubric("behavioral_answer", 1)  # body used as a system prompt
    assert "0 through 5" in technical  # scale is in the file, not hardcoded in ollama.py
    assert "0 through 5" in behavioral  # both rubrics share the integer scale
    with pytest.raises(RubricNotFoundError, match="technical_answer"):  # typed miss, not FileNotFoundError
        load_rubric("technical_answer", 99)  # bumping requires adding the file, not rewriting backends


def test_backends_do_not_hardcode_rubric_wording() -> None:
    """A rubric bump must not require rewriting Ollama/OpenAI-compatible modules."""
    import inspect  # read source at runtime so this fails if someone pastes the rubric into a backend

    ollama_src = inspect.getsource(OllamaBackend)  # HTTP adapter source
    openai_src = inspect.getsource(OpenAICompatBackend)  # HTTP adapter source
    assert "0 through 5" not in ollama_src  # scale lives in the markdown files
    assert "0 through 5" not in openai_src  # same for the other backend
    assert "technical_answer" not in ollama_src  # rubric names live in evaluate_answer / callers
    assert "technical_answer" not in openai_src  # same for the other backend


def test_evaluate_answer_sends_rubric_text_and_returns_typed_evaluation() -> None:
    """evaluate_answer loads the file, puts it in messages, and still enforces AnswerEvaluation."""
    backend = FakeBackend(json.dumps(_VALID_EVALUATION))  # valid judge JSON
    provider = get_provider(backend=backend)  # factory test-double path; no HTTP
    result = evaluate_answer(
        question="What is a Python list?",  # user turn
        answer="A mutable ordered sequence.",  # user turn
        rubric_name="technical_answer",  # file name without _v1.md
        rubric_version=1,  # version suffix
        provider=provider,  # do not construct from env (would try real Ollama if generate were called)
    )
    assert result.score == 4  # parsed from the fake JSON
    assert backend.last_messages is not None  # generate was called
    blobs = [turn["content"] for turn in backend.last_messages]  # system contract + rubric + user
    assert any("0 through 5" in blob for blob in blobs)  # rubric file made it into the prompt
    assert any("Python list" in blob for blob in blobs)  # question made it into the user turn
    assert any("JSON Schema" in blob for blob in blobs)  # complete_json prepends the schema contract


def test_ollama_backend_parses_chat_response_via_mock_transport() -> None:
    """Ollama POST /api/chat: MockTransport proves JSON mode + schema format without a live daemon."""

    def handler(request: httpx.Request) -> httpx.Response:  # httpx calls this instead of the network
        assert request.url.path.endswith("/api/chat")  # Ollama native chat path, not /v1/chat/completions
        body = json.loads(request.content)  # request JSON
        assert body["stream"] is False  # we never consume a token stream
        assert body["keep_alive"] == 0  # unload after the call (8GB VRAM)
        assert isinstance(body["format"], dict)  # Pydantic JSON Schema, not just the string "json"
        assert body["options"]["temperature"] == 0.0  # judge calls are deterministic by default
        return httpx.Response(  # Ollama non-streaming chat shape
            200,
            json={"message": {"role": "assistant", "content": json.dumps(_VALID_EVALUATION)}},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://ollama.test")  # no real socket
    backend = OllamaBackend(client=client)  # injected client: _owned_client stays None
    provider = LLMProvider(backend)  # same facade production uses
    parsed = provider.complete_json([{"role": "user", "content": "score this"}], AnswerEvaluation)
    assert parsed.score == 4  # schema-valid
    client.close()  # test owns the injected client


def test_ollama_backend_http_error_is_provider_error() -> None:
    """A 500 from Ollama is LLMProviderError (transport), not a JSON/schema error."""

    def handler(_request: httpx.Request) -> httpx.Response:  # always fail
        return httpx.Response(500, text="internal error")  # Ollama error body is often plain text/JSON

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://ollama.test")  # no real socket
    backend = OllamaBackend(client=client)  # injected
    with pytest.raises(LLMProviderError, match="500") as caught:  # status is in the message
        backend.generate([{"role": "user", "content": "hi"}])  # generate, not complete_json
    assert caught.value.status_code == 500  # callers can branch on HTTP vs connect failures
    client.close()  # test owns the injected client


def test_openai_compat_backend_parses_chat_completions_via_mock_transport() -> None:
    """OpenAI-compatible POST /chat/completions with json_object mode, no live API key required."""

    def handler(request: httpx.Request) -> httpx.Response:  # httpx calls this instead of the network
        assert request.url.path.endswith("/chat/completions")  # OpenAI path, relative to a /v1 base
        body = json.loads(request.content)  # request JSON
        assert body["response_format"] == {"type": "json_object"}  # widely supported; not json_schema
        assert body["temperature"] == 0.0  # top-level temperature for this API family
        return httpx.Response(  # chat.completions non-streaming shape
            200,
            json={"choices": [{"message": {"role": "assistant", "content": json.dumps(_VALID_EVALUATION)}}]},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://openai.test/v1")  # no real socket
    backend = OpenAICompatBackend(client=client, api_key="")  # empty key is allowed (local clones)
    provider = LLMProvider(backend)  # same facade
    parsed = provider.complete_json([{"role": "user", "content": "score this"}], AnswerEvaluation)
    assert parsed.score == 4  # schema-valid
    client.close()  # test owns the injected client


def test_openai_compat_empty_choices_is_json_error() -> None:
    """A 200 with no choices cannot be schema-validated; it is an empty completion, not a score."""

    def handler(_request: httpx.Request) -> httpx.Response:  # 200 but empty
        return httpx.Response(200, json={"choices": []})  # some gateways do this on refusal

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://openai.test/v1")  # no real socket
    backend = OpenAICompatBackend(client=client)  # injected
    with pytest.raises(LLMJSONError, match="no choices"):  # not a silent score of 0
        LLMProvider(backend).complete_json([{"role": "user", "content": "x"}], AnswerEvaluation)
    client.close()  # test owns the injected client


def test_live_ollama_evaluate_answer_smoke() -> None:
    """One real-Ollama call: skipped (not failed) when the daemon is down or has no pulled models."""
    try:
        tags = httpx.get("http://127.0.0.1:11434/api/tags", timeout=2.0)  # cheap liveness probe
        tags.raise_for_status()  # non-200 means Ollama is up but unhealthy; still skip rather than fail CI
    except Exception as exc:  # connection refused, timeout, DNS — the common offline/CI case
        pytest.skip(f"Ollama not reachable: {exc}")  # never fail the suite for a missing local daemon

    names = [item.get("name") for item in (tags.json().get("models") or []) if item.get("name")]  # pulled tags
    if not names:  # daemon is up but `ollama pull` has not been run
        pytest.skip("Ollama has no models pulled")  # pulling in CI is out of scope

    config = config_from_settings(Settings())  # honor .env via Settings, not os.environ
    if config.provider != "ollama":  # a developer pointing at openai_compat should not hit this smoke
        pytest.skip(f"LLM_PROVIDER={config.provider}; live smoke is Ollama-only")  # hosted keys stay out of CI

    if config.ollama_model not in names:  # .env.example names an 8B tag that may not be pulled locally
        config = replace(config, ollama_model=names[0])  # use whatever *is* pulled so the smoke can still run

    provider = get_provider(config)  # still lazy until evaluate_answer -> complete_json
    try:
        result = evaluate_answer(  # real HTTP + real JSON schema enforcement
            question="What is a Python list?",  # tiny prompt to keep the completion short
            answer="A mutable ordered sequence of objects.",  # tiny answer
            rubric_name="technical_answer",  # shipped v1 file
            provider=provider,  # explicit so we close it in finally
        )
    except LLMProviderError as exc:  # model unload/load race, VRAM pressure — skip, do not fail CI
        pytest.skip(f"Ollama generate failed: {exc}")  # JSON/schema errors below are *not* skipped
    finally:
        provider.close()  # drop the owned httpx client even if skip/assert happens next

    assert 0 <= result.score <= 5  # schema already enforces this; belt-and-suspenders for the smoke
    assert result.rationale  # non-empty justification from the live model
