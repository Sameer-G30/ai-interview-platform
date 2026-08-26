"""Single LLM abstraction the product and a later research harness both call.

Backends (`OllamaBackend`, `OpenAICompatBackend`) only do HTTP. This module owns:

- config (`LLMConfig` / `config_from_settings` / `from_env`) selected by `LLM_PROVIDER`
- `complete_json`: ask for JSON, then enforce a Pydantic schema (no prose fallback)
- `evaluate_answer`: load a versioned rubric file and score one Q&A on the 0-5 scale

HTTP clients stay lazy: constructing a provider does not open a socket or load a model. FastAPI
must not call `get_provider()` at import time — Phase 9's worker is the process that talks to Ollama.
"""

from __future__ import annotations  # allow Protocol/generic forward refs without quotes everywhere

import json  # json.loads of the model reply; json.dumps of the Pydantic JSON Schema into the prompt
import os  # LLMConfig.from_env reads the same names as .env.example / Settings
from dataclasses import dataclass  # LLMConfig is a plain value object, independent of FastAPI Settings
from typing import Any, Protocol, TypeVar  # structural backend typing + generic complete_json

from pydantic import BaseModel, ValidationError  # response_model + the error we wrap as LLMSchemaError

from ml.llm.errors import LLMJSONError, LLMSchemaError, RubricNotFoundError  # typed parse/schema/rubric failures
from ml.llm.ollama import DEFAULT_OLLAMA_BASE_URL, DEFAULT_OLLAMA_MODEL, DEFAULT_TIMEOUT_SECONDS, OllamaBackend
from ml.llm.openai_compat import (
    DEFAULT_OPENAI_COMPAT_BASE_URL,  # hosted default; Settings overrides
    DEFAULT_OPENAI_COMPAT_MODEL,  # hosted default; Settings overrides
    OpenAICompatBackend,  # LLM_PROVIDER=openai_compat
)
from ml.llm.rubrics import load_rubric  # versioned markdown files, not strings hardcoded in backends
from ml.llm.schemas import AnswerEvaluation  # the 0-5 judge schema evaluate_answer returns

T = TypeVar("T", bound=BaseModel)  # complete_json is generic over the caller's Pydantic model

# Allowed LLM_PROVIDER values; anything else is a ValueError at get_provider() (not at FastAPI import).
PROVIDER_OLLAMA = "ollama"
PROVIDER_OPENAI_COMPAT = "openai_compat"

# Default rubric used by evaluate_answer when the caller does not pick one.
DEFAULT_RUBRIC_NAME = "technical_answer"
DEFAULT_RUBRIC_VERSION = 1

# Truncate model dumps in exception.raw_text so logs stay readable.
_RAW_TEXT_LIMIT = 2000


@dataclass(frozen=True)
class LLMConfig:
    """Provider selection and connection settings. Mirrors Settings / .env.example field names.

    This is the only config object `ml.llm` understands. FastAPI Settings holds the same values
    (wired this phase); Phase 9 maps them with `config_from_settings`. The research harness can
    construct `LLMConfig` directly without importing `app.core.config`.
    """

    provider: str = PROVIDER_OLLAMA  # "ollama" | "openai_compat"
    ollama_base_url: str = DEFAULT_OLLAMA_BASE_URL  # local daemon origin
    ollama_model: str = DEFAULT_OLLAMA_MODEL  # Ollama tag; must already be pulled
    openai_compat_base_url: str = DEFAULT_OPENAI_COMPAT_BASE_URL  # include /v1 for OpenAI
    openai_compat_api_key: str = ""  # empty is valid for keyless local servers
    openai_compat_model: str = DEFAULT_OPENAI_COMPAT_MODEL  # remote model id
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS  # httpx read timeout for a completion

    @classmethod
    def from_env(cls) -> LLMConfig:
        """Build from process env using the same names as `.env.example`.

        pydantic-settings loads `.env` into FastAPI `Settings` but does *not* export those keys into
        `os.environ`. Product code should prefer `config_from_settings(get_settings())`. This helper
        is for a research harness that exported the vars (or called `load_dotenv`) itself.
        """
        return cls(
            provider=os.environ.get("LLM_PROVIDER", PROVIDER_OLLAMA).strip().lower() or PROVIDER_OLLAMA,  # selector
            ollama_base_url=(
                os.environ.get("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL).rstrip("/") or DEFAULT_OLLAMA_BASE_URL
            ),  # local daemon origin
            ollama_model=os.environ.get("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL) or DEFAULT_OLLAMA_MODEL,  # Ollama tag
            openai_compat_base_url=(
                os.environ.get("OPENAI_COMPAT_BASE_URL", DEFAULT_OPENAI_COMPAT_BASE_URL).rstrip("/")
                or DEFAULT_OPENAI_COMPAT_BASE_URL
            ),  # include /v1 for OpenAI
            openai_compat_api_key=os.environ.get("OPENAI_COMPAT_API_KEY", "") or "",  # empty is valid
            openai_compat_model=os.environ.get("OPENAI_COMPAT_MODEL", DEFAULT_OPENAI_COMPAT_MODEL)
            or DEFAULT_OPENAI_COMPAT_MODEL,  # remote model id
        )


def config_from_settings(settings: Any) -> LLMConfig:
    """Map a Settings-like object (duck-typed) onto `LLMConfig` without importing FastAPI.

    Phase 9 will call `config_from_settings(get_settings())`. Tests can pass a SimpleNamespace.
    """
    return LLMConfig(
        provider=str(settings.llm_provider).strip().lower(),  # Settings field llm_provider <- LLM_PROVIDER
        ollama_base_url=str(settings.ollama_base_url).rstrip("/"),  # Settings field ollama_base_url
        ollama_model=str(settings.ollama_model),  # Settings field ollama_model
        openai_compat_base_url=str(settings.openai_compat_base_url).rstrip("/"),  # OPENAI_COMPAT_BASE_URL
        openai_compat_api_key=str(settings.openai_compat_api_key or ""),  # may be None if unset; normalize to ""
        openai_compat_model=str(settings.openai_compat_model),  # Settings field openai_compat_model
    )


class LLMBackend(Protocol):
    """HTTP adapter surface. Backends return raw assistant text; they do not parse JSON themselves."""

    name: str  # "ollama" or "openai_compat"

    def generate(
        self,
        messages: list[dict[str, str]],  # {role, content} turns
        *,
        temperature: float = 0.0,  # sampler temperature
        json_schema: dict[str, Any] | None = None,  # optional JSON Schema for backends that constrain decoding
    ) -> str:  # assistant content, still a string
        """Return the assistant message body (expected to be JSON text)."""
        ...

    def close(self) -> None:
        """Release any owned HTTP client."""
        ...


def _truncate(text: str, limit: int = _RAW_TEXT_LIMIT) -> str:
    """Cap exception.raw_text so a huge completion cannot blow up logs."""
    if len(text) <= limit:  # common case: a short JSON object
        return text  # keep it exactly as returned
    return text[:limit] + "...(truncated)"  # mark that we cut it so readers do not think the model stopped there


def parse_structured(raw_text: str, response_model: type[T]) -> T:
    """JSON-decode `raw_text` and validate it as `response_model`.

    Invalid JSON -> `LLMJSONError`. Valid JSON that fails the schema -> `LLMSchemaError`.
    There is no third path that returns free text, strips markdown fences, or clamps out-of-range scores.
    """
    try:
        data = json.loads(raw_text)  # strictly JSON; markdown fences and leading prose fail here
    except json.JSONDecodeError as exc:  # the model replied with something that is not JSON
        raise LLMJSONError(
            f"model did not return valid JSON: {exc}",
            raw_text=_truncate(raw_text),
        ) from exc
    try:
        return response_model.model_validate(data)  # Pydantic v2: extra keys ignored; missing/out-of-range fail
    except ValidationError as exc:  # score 7, missing rationale, wrong types, ...
        raise LLMSchemaError(
            f"JSON did not match {response_model.__name__}: {exc}",
            raw_text=_truncate(raw_text),
        ) from exc


def _json_schema_for(response_model: type[BaseModel]) -> dict[str, Any]:
    """Pydantic JSON Schema handed to Ollama `format` and copied into the system prompt."""
    return response_model.model_json_schema()  # simple models have no $defs; nested ones keep them


def _messages_with_json_contract(messages: list[dict[str, str]], schema: dict[str, Any]) -> list[dict[str, str]]:
    """Prepend a system turn that states the JSON contract. Does not attempt to repair bad replies later."""
    contract = (
        "You MUST reply with a single JSON object matching this JSON Schema. "
        "Do not include markdown fences or any text outside the JSON object.\n\n"
        f"{json.dumps(schema)}"
    )
    extra = {"role": "system", "content": contract}  # first turn so both backends see the schema
    return [extra, *messages]  # caller messages (rubric + user) follow unchanged


class LLMProvider:
    """Facade used by the product: `complete_json` + `evaluate_answer` over any `LLMBackend`."""

    def __init__(self, backend: LLMBackend) -> None:
        self.backend = backend  # public so tests can isinstance() / assert backend.name

    @property
    def name(self) -> str:
        """The backend's selector string (`ollama` or `openai_compat`)."""
        return self.backend.name  # matches LLM_PROVIDER

    def close(self) -> None:
        """Close the backend's owned HTTP client, if any."""
        self.backend.close()  # injected mock clients are left open by the backend

    def complete_json(
        self,
        messages: list[dict[str, str]],
        response_model: type[T],
        *,
        temperature: float = 0.0,
    ) -> T:
        """Call the backend, then parse+validate the reply as `response_model`.

        Failures are `LLMJSONError` / `LLMSchemaError` / `LLMProviderError` — never a string.
        """
        schema = _json_schema_for(response_model)  # same schema goes into the prompt and Ollama `format`
        prompted = _messages_with_json_contract(messages, schema)  # backends do not add this themselves
        raw = self.backend.generate(prompted, temperature=temperature, json_schema=schema)  # HTTP happens here
        return parse_structured(raw, response_model)  # typed error if the reply is not valid JSON+schema

    def evaluate_answer(
        self,
        question: str,
        answer: str,
        *,
        rubric_name: str = DEFAULT_RUBRIC_NAME,
        rubric_version: int = DEFAULT_RUBRIC_VERSION,
        temperature: float = 0.0,
    ) -> AnswerEvaluation:
        """Score one question/answer pair using a versioned rubric file and `AnswerEvaluation`.

        This is still the provider library (no session, no question generation). Phase 9's worker
        will call this inside `asyncio.to_thread` — never from a FastAPI request handler.
        """
        rubric_text = load_rubric(rubric_name, rubric_version)  # FileNotFound -> RubricNotFoundError
        messages = [
            {"role": "system", "content": rubric_text},  # 0-5 instructions from the file, not from this function
            {
                "role": "user",
                "content": f"Question:\n{question}\n\nCandidate answer:\n{answer}",
            },
        ]
        return self.complete_json(messages, AnswerEvaluation, temperature=temperature)  # schema-enforced 0-5


def get_provider(config: LLMConfig | None = None, *, backend: LLMBackend | None = None) -> LLMProvider:
    """Factory: pick Ollama or OpenAI-compatible from `config.provider`.

    `backend=` is for tests (fake generate()). Production passes `LLMConfig` only. `config is None`
    falls back to `LLMConfig.from_env()`; product code should pass `config_from_settings(...)`.
    """
    if backend is not None:  # tests inject a fake that never opens HTTP
        return LLMProvider(backend)  # ignore config; the fake is the whole backend
    resolved = config or LLMConfig.from_env()  # research-harness convenience when env vars are exported
    name = resolved.provider.strip().lower()  # tolerate LLM_PROVIDER=Ollama
    if name == PROVIDER_OLLAMA:
        return LLMProvider(
            OllamaBackend(
                base_url=resolved.ollama_base_url,
                model=resolved.ollama_model,
                timeout_seconds=resolved.timeout_seconds,
            )
        )
    if name == PROVIDER_OPENAI_COMPAT:
        return LLMProvider(
            OpenAICompatBackend(
                base_url=resolved.openai_compat_base_url,
                model=resolved.openai_compat_model,
                api_key=resolved.openai_compat_api_key,
                timeout_seconds=resolved.timeout_seconds,
            )
        )
    raise ValueError(
        f"unknown LLM provider: {resolved.provider!r} (expected {PROVIDER_OLLAMA!r} or {PROVIDER_OPENAI_COMPAT!r})"
    )


def evaluate_answer(
    question: str,
    answer: str,
    *,
    rubric_name: str = DEFAULT_RUBRIC_NAME,
    rubric_version: int = DEFAULT_RUBRIC_VERSION,
    provider: LLMProvider | None = None,
    config: LLMConfig | None = None,
    temperature: float = 0.0,
) -> AnswerEvaluation:
    """Module-level entry point matching `ml.resume.run_resume_pipeline` / `ml.matching.get_backend`.

    Pass an explicit `provider` in tests. Production (Phase 9) should pass a provider built from
    Settings so `.env` is honored (pydantic-settings does not populate `os.environ`).
    """
    resolved = provider or get_provider(config)  # constructing here still does not open HTTP until complete_json
    return resolved.evaluate_answer(
        question,
        answer,
        rubric_name=rubric_name,
        rubric_version=rubric_version,
        temperature=temperature,
    )


# Re-export so `from ml.llm.provider import RubricNotFoundError` works next to the factory.
__all__ = [
    "DEFAULT_RUBRIC_NAME",
    "DEFAULT_RUBRIC_VERSION",
    "LLMBackend",
    "LLMConfig",
    "LLMProvider",
    "PROVIDER_OLLAMA",
    "PROVIDER_OPENAI_COMPAT",
    "config_from_settings",
    "evaluate_answer",
    "get_provider",
    "parse_structured",
    "RubricNotFoundError",
]
