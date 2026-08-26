"""Pluggable LLM provider: Ollama (local default) and OpenAI-compatible HTTP, with Pydantic JSON output.

This package is the library. Phase 9 (interview-engine) is the ARQ worker that will call it inside
`asyncio.to_thread`. Do not import `get_provider()` from FastAPI request handlers or at app import time —
the judge model must not be loaded in the API process (8GB VRAM budget).
"""

from ml.llm.errors import (  # typed failures
    LLMError,
    LLMJSONError,
    LLMProviderError,
    LLMSchemaError,
    RubricNotFoundError,
)
from ml.llm.ollama import OllamaBackend  # local default backend (HTTP to Ollama, lazy client)
from ml.llm.openai_compat import OpenAICompatBackend  # hosted / OpenAI-compatible backend (lazy client)
from ml.llm.provider import (
    LLMConfig,
    LLMProvider,
    config_from_settings,
    evaluate_answer,
    get_provider,
    parse_structured,
)
from ml.llm.rubrics import list_rubrics, load_rubric  # versioned 0-5 rubric markdown files
from ml.llm.schemas import AnswerEvaluation  # structured judge output (score 0-5 + rationale)

__all__ = [  # public surface the worker and research harness should import from `ml.llm`
    "AnswerEvaluation",  # Pydantic judge schema
    "LLMConfig",  # provider selection + connection settings
    "LLMError",  # base error
    "LLMJSONError",  # invalid JSON from the model
    "LLMProvider",  # facade with complete_json / evaluate_answer
    "LLMProviderError",  # HTTP / transport failure
    "LLMSchemaError",  # JSON that fails the Pydantic schema
    "OllamaBackend",  # LLM_PROVIDER=ollama
    "OpenAICompatBackend",  # LLM_PROVIDER=openai_compat
    "RubricNotFoundError",  # missing rubric file
    "config_from_settings",  # Settings -> LLMConfig
    "evaluate_answer",  # module-level 0-5 scoring entry point
    "get_provider",  # factory
    "list_rubrics",  # discover shipped rubric files
    "load_rubric",  # load one versioned rubric body
    "parse_structured",  # JSON + Pydantic enforcement helper
]
