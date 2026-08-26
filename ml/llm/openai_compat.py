"""OpenAI-compatible HTTP backend: POST /chat/completions with `response_format: json_object`.

Works against OpenAI, Groq, vLLM, llama.cpp, and Ollama's `/v1` compatibility surface. The client is
created on first `generate()` so importing this module never opens a socket or requires an API key.
A missing key is a typed `LLMProviderError` at call time, not at construction — local compatible
servers often need no key at all.
"""

import json  # re-serializes a content object if a gateway already decoded the JSON
from typing import Any  # JSON payload / response dicts are untyped vendor shapes

import httpx  # light HTTP client; constructed lazily in `_ensure_client`, not at import or `__init__`

from ml.llm.errors import LLMJSONError, LLMProviderError  # transport vs empty-body failures

# Default hosted origin including the `/v1` suffix the chat-completions path is relative to.
DEFAULT_OPENAI_COMPAT_BASE_URL = "https://api.openai.com/v1"

# Default hosted model name; overridden by OPENAI_COMPAT_MODEL in Settings / .env.
DEFAULT_OPENAI_COMPAT_MODEL = "gpt-4o-mini"

# Generation timeout; matches the Ollama backend so swapping providers does not change the budget.
DEFAULT_TIMEOUT_SECONDS = 120.0


class OpenAICompatBackend:
    """`LLMBackend` implementation for any server that speaks OpenAI chat-completions JSON mode."""

    name = "openai_compat"  # factory / tests compare this string; must match LLM_PROVIDER=openai_compat

    def __init__(
        self,
        base_url: str = DEFAULT_OPENAI_COMPAT_BASE_URL,  # must include `/v1` for OpenAI; Ollama uses `http://host:11434/v1`
        model: str = DEFAULT_OPENAI_COMPAT_MODEL,  # model id the remote server recognizes
        api_key: str = "",  # Bearer token; empty is allowed for keyless local servers
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,  # read timeout for a completion
        client: httpx.Client | None = None,  # tests inject MockTransport clients; production leaves this None
    ) -> None:
        self._base_url = base_url.rstrip("/")  # httpx join is reliable without a trailing slash
        self._model = model  # sent as the `model` field on every /chat/completions call
        self._api_key = api_key  # not sent as a header when empty, so local servers are not forced to auth
        self._timeout_seconds = timeout_seconds  # applied when we first construct an owned client
        self._injected_client = client  # if set, `_ensure_client` never opens a real socket
        self._owned_client: httpx.Client | None = None  # created on first generate(); closed by close()

    def _ensure_client(self) -> httpx.Client:
        """Return the injected client, or construct one owned client on first use."""
        if self._injected_client is not None:  # tests: MockTransport, never hit the network
            return self._injected_client  # caller owns its lifecycle
        if self._owned_client is None:  # first real generate() in this process
            headers: dict[str, str] = {}  # Authorization is optional; Content-Type is set by httpx json=
            if self._api_key:  # hosted OpenAI-compatible APIs require a Bearer token
                headers["Authorization"] = f"Bearer {self._api_key}"  # never log this header
            self._owned_client = httpx.Client(  # not created at import, not created in __init__
                base_url=self._base_url,  # /chat/completions is resolved against this origin
                timeout=httpx.Timeout(self._timeout_seconds, connect=5.0),  # fail fast if the host is down
                headers=headers,  # empty dict when no key, so keyless local servers still work
            )
        return self._owned_client  # reuse the connection pool across worker jobs in this process

    def close(self) -> None:
        """Close an owned httpx client. Injected clients are left alone (the test owns them)."""
        if self._owned_client is not None:  # never constructed in the lazy-init / injected-only cases
            self._owned_client.close()  # drop pooled connections so the process can exit cleanly
            self._owned_client = None  # allow a later generate() to open a fresh client if needed

    def generate(
        self,
        messages: list[dict[str, str]],  # OpenAI-style {role, content} dicts
        *,
        temperature: float = 0.0,  # 0 = as deterministic as the sampler allows for a judge call
        json_schema: dict[str, Any] | None = None,  # accepted for interface parity; JSON-mode does not send it
    ) -> str:
        """POST /chat/completions and return the assistant message content as a string (still unparsed JSON)."""
        del json_schema  # openai_compat uses widely-supported json_object mode, not json_schema (many clones 400)
        payload: dict[str, Any] = {  # request body matching Chat Completions
            "model": self._model,  # remote model id
            "messages": messages,  # system + user turns already include the rubric and schema contract
            "temperature": temperature,  # top-level for OpenAI; Ollama-compat servers honor this too
            "response_format": {"type": "json_object"},  # ask for JSON; Pydantic still validates the body
        }
        client = self._ensure_client()  # may open the owned client on this first call
        try:
            response = client.post("/chat/completions", json=payload)  # path is relative to base_url
            response.raise_for_status()  # 4xx/5xx become HTTPStatusError, wrapped below
        except httpx.HTTPStatusError as exc:  # unknown model, bad key, unsupported response_format, ...
            snippet = exc.response.text[:500]  # short body for the message; full body stays on the response
            raise LLMProviderError(
                f"OpenAI-compatible HTTP {exc.response.status_code}: {snippet}",
                status_code=exc.response.status_code,
            ) from exc
        except httpx.RequestError as exc:  # DNS, connection refused, timeout
            raise LLMProviderError(f"OpenAI-compatible request failed: {exc}") from exc
        try:
            data = response.json()  # non-streaming chat.completions returns one JSON object
        except ValueError as exc:  # body was not JSON at all (proxy HTML, truncated)
            raise LLMProviderError("OpenAI-compatible server returned a non-JSON response body") from exc
        choices = data.get("choices") or []  # missing/empty choices is an empty completion, not valid JSON
        if not choices:  # no assistant message to parse
            raise LLMJSONError("OpenAI-compatible server returned no choices", raw_text=str(data)[:2000])
        content = (choices[0].get("message") or {}).get("content")  # first choice is the completion we asked for
        if content is None:  # refusal / empty content cannot be schema-validated
            raise LLMJSONError("OpenAI-compatible server returned no message.content", raw_text=str(data)[:2000])
        if isinstance(content, str):  # normal case: JSON (or prose) as a string
            return content  # caller (LLMProvider.complete_json) parses and validates
        return json.dumps(content)  # already-decoded object: re-serialize so parse_structured still runs
