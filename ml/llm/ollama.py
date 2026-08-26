"""Ollama HTTP backend: POST /api/chat with JSON/schema `format`, no model weights in this process.

Ollama itself loads the GGUF into VRAM in *its* process. This module only opens an httpx client on
the first `generate()` call so importing FastAPI (or `ml.llm`) never talks to port 11434. `keep_alive`
is 0 so the judge unloads after each call — an 8GB GPU cannot comfortably hold a 7-8B judge plus Whisper.
"""

import json  # re-serializes a content object if a gateway already decoded the JSON
from typing import Any  # JSON payload / response dicts are untyped vendor shapes

import httpx  # light HTTP client; constructed lazily in `_ensure_client`, not at import or `__init__`

from ml.llm.errors import LLMJSONError, LLMProviderError  # transport vs empty-body failures

# Default local daemon address; Settings / .env override this via LLMConfig.
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"

# Default tag from .env.example; sized as a Q4_K_M 8B instruct model for an 8GB card.
DEFAULT_OLLAMA_MODEL = "llama3.1:8b-instruct-q4_K_M"

# Generation can include a cold model load; httpx's 5s default is far too short.
DEFAULT_TIMEOUT_SECONDS = 120.0

# Unload immediately after the response so VRAM is free for the next worker job (Whisper, SBERT, ...).
_KEEP_ALIVE_UNLOAD = 0


class OllamaBackend:
    """`LLMBackend` implementation that talks to a local Ollama daemon over HTTP."""

    name = "ollama"  # factory / tests compare this string; must match LLM_PROVIDER=ollama

    def __init__(
        self,
        base_url: str = DEFAULT_OLLAMA_BASE_URL,  # e.g. http://localhost:11434, no trailing path
        model: str = DEFAULT_OLLAMA_MODEL,  # Ollama model tag already pulled via `ollama pull`
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,  # read timeout for a cold load + completion
        client: httpx.Client | None = None,  # tests inject MockTransport clients; production leaves this None
    ) -> None:
        self._base_url = base_url.rstrip("/")  # httpx join is reliable without a trailing slash
        self._model = model  # sent as the `model` field on every /api/chat call
        self._timeout_seconds = timeout_seconds  # applied when we first construct an owned client
        self._injected_client = client  # if set, `_ensure_client` never opens a real socket
        self._owned_client: httpx.Client | None = None  # created on first generate(); closed by close()

    def _ensure_client(self) -> httpx.Client:
        """Return the injected client, or construct one owned client on first use."""
        if self._injected_client is not None:  # tests: MockTransport, never hit the network
            return self._injected_client  # caller owns its lifecycle
        if self._owned_client is None:  # first real generate() in this process
            self._owned_client = httpx.Client(  # not created at import, not created in __init__
                base_url=self._base_url,  # /api/chat is resolved against this origin
                timeout=httpx.Timeout(self._timeout_seconds, connect=5.0),  # fail fast if Ollama is down
            )
        return self._owned_client  # reuse the connection pool across worker jobs in this process

    def close(self) -> None:
        """Close an owned httpx client. Injected clients are left alone (the test owns them)."""
        if self._owned_client is not None:  # never constructed in the lazy-init / injected-only cases
            self._owned_client.close()  # drop pooled connections so the process can exit cleanly
            self._owned_client = None  # allow a later generate() to open a fresh client if needed

    def generate(
        self,
        messages: list[dict[str, str]],  # OpenAI-style {role, content} dicts; Ollama accepts the same shape
        *,
        temperature: float = 0.0,  # 0 = as deterministic as the sampler allows for a judge call
        json_schema: dict[str, Any] | None = None,  # Pydantic JSON Schema, passed as Ollama `format`
    ) -> str:
        """POST /api/chat and return the assistant message content as a string (still unparsed JSON)."""
        payload: dict[str, Any] = {  # request body matching Ollama's ChatRequest
            "model": self._model,  # must already be pulled; missing tags become HTTP 404 -> LLMProviderError
            "messages": messages,  # system + user turns already include the rubric and schema contract
            "stream": False,  # a single JSON object is much easier to validate than a token stream
            "keep_alive": _KEEP_ALIVE_UNLOAD,  # 0 = unload after this call (8GB VRAM budget)
            "options": {"temperature": temperature},  # sampler options nested per Ollama's API
            "format": json_schema if json_schema is not None else "json",  # schema when we have one, else json mode
        }
        client = self._ensure_client()  # may open the owned client on this first call
        try:
            response = client.post("/api/chat", json=payload)  # path is relative to base_url
            response.raise_for_status()  # 4xx/5xx become HTTPStatusError, wrapped below
        except httpx.HTTPStatusError as exc:  # Ollama returned an error JSON (unknown model, bad request, ...)
            snippet = exc.response.text[:500]  # short body for the message; full body stays on the response
            raise LLMProviderError(
                f"Ollama HTTP {exc.response.status_code}: {snippet}",
                status_code=exc.response.status_code,
            ) from exc
        except httpx.RequestError as exc:  # DNS, connection refused, timeout — Ollama is not reachable
            raise LLMProviderError(f"Ollama request failed: {exc}") from exc
        try:
            data = response.json()  # non-streaming /api/chat returns one JSON object
        except ValueError as exc:  # body was not JSON at all (proxy HTML, truncated)
            raise LLMProviderError("Ollama returned a non-JSON response body") from exc
        content = (data.get("message") or {}).get("content")  # chat endpoint nests the text here
        if content is None:  # missing assistant message is treated as "not JSON we can validate"
            raise LLMJSONError("Ollama returned no message.content", raw_text=str(data)[:2000])
        if isinstance(content, str):  # normal case: JSON (or prose) as a string
            return content  # caller (LLMProvider.complete_json) parses and validates
        # Some gateways decode `format` JSON into an object; re-serialize so parse_structured still runs.
        return json.dumps(content)  # parse_structured json.loads this back and then Pydantic-validates
