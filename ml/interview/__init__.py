"""Interview engine helpers used by the Phase 9 ARQ worker (not by FastAPI request handlers).

Question generation and follow-up text still go through `ml.llm.complete_json` / `evaluate_answer`.
This package owns the deterministic follow-up *rule* and the prompt builders so those can be
unit-tested with a fake provider and never run inline in an HTTP handler.
"""

from ml.interview.followup import FOLLOW_UP_SCORE_MAX, should_follow_up  # score <= 2 and not already a follow-up
from ml.interview.prompts import (  # message lists handed to LLMProvider.complete_json
    DEFAULT_QUESTION_COUNT,
    build_followup_messages,
    build_generate_messages,
    rubric_name_for_kind,
)

__all__ = [  # public surface the worker imports from `ml.interview`
    "DEFAULT_QUESTION_COUNT",  # how many questions the generate prompt asks for
    "FOLLOW_UP_SCORE_MAX",  # inclusive score ceiling that warrants one follow-up
    "build_followup_messages",  # complete_json messages for a single follow-up question
    "build_generate_messages",  # complete_json messages for the initial question list
    "rubric_name_for_kind",  # technical -> technical_answer, behavioral -> behavioral_answer
    "should_follow_up",  # deterministic follow-up predicate
]
