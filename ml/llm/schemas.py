"""Pydantic models that define the only structured outputs this provider will accept.

The interview engine (Phase 9) and a later research harness both call `complete_json(..., response_model=...)`.
Keeping the schemas here — not inside a backend file — means bumping a field never requires rewriting
Ollama vs OpenAI-compatible HTTP payloads.
"""

from pydantic import BaseModel, Field  # Field carries 0-5 bounds and descriptions that flow into JSON Schema


class AnswerEvaluation(BaseModel):
    """Judge output for one interview answer, scored on the versioned 0-5 rubric files.

    Extra keys the model may emit are ignored (Pydantic default), but a missing required field or a
    score outside 0-5 is a `ValidationError` that the provider turns into `LLMSchemaError` — never a
    silent clamp or a free-text fallback.
    """

    score: int = Field(  # integer, not float: the rubric files describe discrete 0-5 buckets
        ge=0,  # below 0 is a schema failure, not a value to clip
        le=5,  # above 5 is a schema failure, not a value to clip
        description="Integer score on the 0-5 rubric scale defined by the loaded rubric file.",
    )
    rationale: str = Field(  # required: a score without a reason is not useful for later explanations
        min_length=1,  # empty string is a schema failure so the judge cannot skip justification
        description="Short justification for the score, citing what the answer did or failed to do.",
    )
    strengths: list[str] = Field(  # required list; empty is allowed when there is nothing positive to say
        description="Concrete things the answer did well; empty list when the score is 0 or the answer is blank.",
    )
    improvements: list[str] = Field(  # required list; empty is allowed for a perfect 5
        description="Concrete gaps or next steps; empty list when the answer already meets the top of the rubric.",
    )
