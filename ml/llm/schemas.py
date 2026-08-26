"""Pydantic models that define the only structured outputs this provider will accept.

The interview engine (Phase 9) and a later research harness both call `complete_json(..., response_model=...)`.
Keeping the schemas here — not inside a backend file — means bumping a field never requires rewriting
Ollama vs OpenAI-compatible HTTP payloads.
"""

from typing import Literal  # question_kind is a closed set so complete_json cannot invent a third rubric

from pydantic import BaseModel, Field  # Field carries 0-5 bounds and descriptions that flow into JSON Schema

# Stored on answers.question_kind and used to pick technical_answer_v1 vs behavioral_answer_v1.
QuestionKind = Literal["technical", "behavioral"]  # closed set; anything else is LLMSchemaError


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


class InterviewQuestion(BaseModel):
    """One interview question produced by `complete_json` (initial generate or a single follow-up).

    `question_kind` selects the versioned rubric file at evaluation time. It is a schema field, not
    something parsed out of the question prose.
    """

    question_text: str = Field(  # the candidate-facing prompt; stored on answers.question_text
        min_length=1,  # empty string is a schema failure so the model cannot skip the question
        description="The question to ask the candidate, as plain text with no markdown fences.",
    )
    question_kind: QuestionKind = Field(  # closed literal; unknown strings are LLMSchemaError
        default="technical",  # omitted kind is still valid JSON; evaluate then uses technical_answer_v1
        description="Which 0-5 rubric to use when scoring the answer: technical or behavioral.",
    )


class GeneratedQuestions(BaseModel):
    """Question-generation payload: a short list of `InterviewQuestion` items in display order.

    `min_length=1` so an empty list is a schema failure (not a silent 'no questions' session).
    `max_length=6` caps a runaway model so a session cannot be stuffed with dozens of rows.
    """

    questions: list[InterviewQuestion] = Field(  # 1-6 items; the worker persists them as answers rows
        min_length=1,  # at least one question or the generate job fails
        max_length=6,  # hard cap; the prompt asks for 4, this is the safety bound
        description="Interview questions for this session, in the order they should be asked.",
    )
