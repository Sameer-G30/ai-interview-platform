"""Deterministic follow-up rule used after `evaluate_answer` returns an `AnswerEvaluation`.

The worker calls this *after* the judge succeeds. A True result means the worker may call
`complete_json` for one `InterviewQuestion` and append it as the next `answers` row. The request
handler never decides follow-ups.
"""

from ml.llm.schemas import AnswerEvaluation  # judge payload: score 0-5 plus improvements list

# Inclusive ceiling: scores 0, 1, or 2 warrant a follow-up. 3+ is "adequate" on the rubric files
# and must not spawn extra questions even if `improvements` is a non-empty coaching list.
FOLLOW_UP_SCORE_MAX = 2


def should_follow_up(evaluation: AnswerEvaluation, *, is_follow_up: bool) -> bool:
    """Return True when this answer should spawn exactly one follow-up question.

    Rule (documented for tests and the README):
    - `evaluation.score <= FOLLOW_UP_SCORE_MAX` (0, 1, or 2 on the 0-5 rubric).
    - The question being scored is *not* already a follow-up (`is_follow_up` is False).

    A follow-up is never followed by another follow-up, so a weak answer to the probe still
    ends the chain. `improvements` being non-empty is *not* used: a score-4 answer often still
    has coaching notes, and that would over-generate.
    """
    if is_follow_up:  # already probing a gap; do not chain a third question off this one
        return False  # session completes once this follow-up is answered (if nothing else is open)
    return evaluation.score <= FOLLOW_UP_SCORE_MAX  # weak original answer -> one targeted probe
