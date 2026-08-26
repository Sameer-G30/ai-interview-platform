"""Typed errors for the LLM provider.

Callers (Phase 9 workers, the research harness, tests) catch these instead of scraping free-text
model output. Invalid JSON and schema failures stay distinct so a retry/fallback policy can treat
"the model rambled" differently from "the model returned JSON that is the wrong shape".
"""


class LLMError(Exception):
    """Base class for every `ml.llm` failure; lets callers catch broadly when they do not care which kind."""


class LLMJSONError(LLMError):
    """Raised when the model reply is not valid JSON (prose, markdown fences, truncated output, empty body).

    `raw_text` is the truncated model reply so logs can show *why* parsing failed without dumping a
    multi-kilobyte completion into every traceback.
    """

    def __init__(self, message: str, raw_text: str = "") -> None:  # message is the human-readable reason
        super().__init__(message)  # Exception stores message as str(self)
        self.raw_text = raw_text  # truncated assistant text, empty when the backend returned no body at all


class LLMSchemaError(LLMError):
    """Raised when the reply is JSON but does not match the Pydantic model (wrong types, score out of 0-5).

    This is not retried as free text: a score of 7 on a 0-5 rubric is a hard failure, not a value to clamp.
    """

    def __init__(self, message: str, raw_text: str = "") -> None:  # message includes the Pydantic error summary
        super().__init__(message)  # Exception stores message as str(self)
        self.raw_text = raw_text  # truncated JSON/text that failed validation, for logs/tests


class LLMProviderError(LLMError):
    """Raised on transport/HTTP failures (connection refused, 4xx/5xx, missing API key at call time).

    Construction of a backend never raises this — the HTTP client is lazy — so importing FastAPI
    does not depend on Ollama being up.
    """

    def __init__(self, message: str, status_code: int | None = None) -> None:  # status_code is None for connect errors
        super().__init__(message)  # Exception stores message as str(self)
        self.status_code = status_code  # HTTP status when we got a response; None when the socket never connected


class RubricNotFoundError(LLMError):
    """Raised when `load_rubric(name, version)` cannot find `ml/llm/rubrics/{name}_v{version}.md`."""
