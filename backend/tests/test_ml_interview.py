"""Unit tests for the Phase 9 follow-up rule and prompt builders (no Postgres/Redis/Ollama)."""

from ml.interview import (  # follow-up rule + prompt builders; no HTTP
    FOLLOW_UP_SCORE_MAX,  # inclusive score ceiling that warrants a follow-up
    build_followup_messages,  # complete_json turns for one follow-up question
    build_generate_messages,  # complete_json turns for the initial question list
    rubric_name_for_kind,  # technical -> technical_answer; behavioral -> behavioral_answer
    should_follow_up,  # score <= 2 and not already a follow-up
)
from ml.llm.schemas import AnswerEvaluation  # judge payload the follow-up rule inspects


def _eval(score: int, improvements: list[str] | None = None) -> AnswerEvaluation:
    """Build a valid AnswerEvaluation; improvements default to one item so a non-empty list is not special."""
    return AnswerEvaluation(
        score=score,  # 0-5 inclusive
        rationale="test rationale",  # min_length=1
        strengths=[],  # empty is allowed
        improvements=improvements if improvements is not None else ["add an example"],  # often non-empty even at 4
    )


def test_should_follow_up_when_score_at_or_below_threshold() -> None:
    """Scores 0, 1, and 2 on an original question warrant exactly one follow-up."""
    assert FOLLOW_UP_SCORE_MAX == 2  # documented ceiling; tests pin the product rule
    assert should_follow_up(_eval(0), is_follow_up=False) is True  # no attempt
    assert should_follow_up(_eval(1), is_follow_up=False) is True  # major gaps
    assert should_follow_up(_eval(2), is_follow_up=False) is True  # partial / would fail a screen


def test_should_not_follow_up_when_score_above_threshold() -> None:
    """Score 3+ is adequate on the rubric; non-empty improvements must not spawn a follow-up."""
    assert should_follow_up(_eval(3, improvements=["go deeper"]), is_follow_up=False) is False
    assert should_follow_up(_eval(4, improvements=["add an example"]), is_follow_up=False) is False
    assert should_follow_up(_eval(5, improvements=[]), is_follow_up=False) is False  # still no follow-up


def test_should_not_follow_up_when_question_is_already_a_follow_up() -> None:
    """A weak answer to the probe must not chain a third question."""
    assert should_follow_up(_eval(0), is_follow_up=True) is False  # even a 0 on a follow-up ends the chain
    assert should_follow_up(_eval(2), is_follow_up=True) is False


def test_rubric_name_for_kind() -> None:
    """question_kind selects the versioned rubric stem; unknown values fall back to technical."""
    assert rubric_name_for_kind("technical") == "technical_answer"  # technical_answer_v1.md
    assert rubric_name_for_kind("behavioral") == "behavioral_answer"  # behavioral_answer_v1.md
    assert rubric_name_for_kind("unknown") == "technical_answer"  # do not invent a third rubric file


def test_generate_messages_include_posting_and_skills() -> None:
    """The generate prompt carries posting title/description/skills and resume skills, not prose to parse later."""
    messages = build_generate_messages(
        resume_skills=["Python", "Docker"],
        posting_title="Backend Engineer",
        posting_description="Build APIs with FastAPI.",
        posting_required_skills="Python, FastAPI",
    )
    assert messages[0]["role"] == "system"  # instructions
    blob = messages[1]["content"]  # user turn with the session facts
    assert "Backend Engineer" in blob  # posting title
    assert "FastAPI" in blob  # posting description / required skills
    assert "Python" in blob  # resume skill
    assert "Docker" in blob  # resume skill


def test_followup_messages_include_score_and_improvements() -> None:
    """The follow-up prompt is built from the judged Q&A, not from free-text scraping."""
    evaluation = _eval(1, improvements=["mention Big-O"])
    messages = build_followup_messages(
        question_text="What is a hash map?",
        answer_text="A list.",
        evaluation=evaluation,
        question_kind="technical",
    )
    blob = messages[1]["content"]  # user turn
    assert "What is a hash map?" in blob  # original question
    assert "A list." in blob  # candidate answer
    assert "1" in blob  # judge score
    assert "mention Big-O" in blob  # judge improvements
