"""Prompt builders for question generation and follow-up. Output is always structured via Pydantic.

These functions return OpenAI-style `{role, content}` message lists. They do not call the LLM;
the worker passes the list to `LLMProvider.complete_json` / `evaluate_answer`.
"""

from ml.llm.schemas import AnswerEvaluation, QuestionKind  # kind picks the rubric; evaluation feeds follow-up

# How many questions the generate prompt asks for. The Pydantic schema still allows 1-6 so a model
# that returns 3 is accepted; tests use a fake backend that returns 2.
DEFAULT_QUESTION_COUNT = 4

# Maps answers.question_kind onto the versioned rubric *name* (without `_v1`); load_rubric adds the version.
_RUBRIC_NAME_BY_KIND: dict[str, str] = {
    "technical": "technical_answer",  # ml/llm/rubrics/technical_answer_v1.md
    "behavioral": "behavioral_answer",  # ml/llm/rubrics/behavioral_answer_v1.md
}


def rubric_name_for_kind(question_kind: str) -> str:
    """Return the rubric file stem for an answers.question_kind value; unknown kinds use technical."""
    return _RUBRIC_NAME_BY_KIND.get(question_kind, "technical_answer")  # default matches evaluate_answer's default


def build_generate_messages(
    *,
    resume_skills: list[str],
    posting_title: str | None,
    posting_description: str | None,
    posting_required_skills: str | None,
    question_count: int = DEFAULT_QUESTION_COUNT,
) -> list[dict[str, str]]:
    """Build the user/system turns for initial question generation from role + extracted skills."""
    skills_text = ", ".join(resume_skills) if resume_skills else "(none extracted)"  # ESCO preferred labels
    title_text = posting_title.strip() if posting_title else "(practice interview; no job posting)"  # optional job_id
    description_text = posting_description.strip() if posting_description else "(none)"  # posting body or placeholder
    required_text = posting_required_skills.strip() if posting_required_skills else "(none)"  # freeform required_skills
    system = (  # tells the model what to produce; the JSON schema is prepended by complete_json
        "You generate interview questions for a hiring screen. "
        f"Produce exactly {question_count} questions mixing technical and behavioral kinds. "
        "Target the posting's role and required skills when a posting is provided; "
        "otherwise target the candidate's extracted skills. "
        "Each question must be a single clear prompt the candidate can answer in text."
    )
    user = (  # the only session-specific facts the model should use
        f"Role title:\n{title_text}\n\n"
        f"Role description:\n{description_text}\n\n"
        f"Required skills:\n{required_text}\n\n"
        f"Candidate extracted skills:\n{skills_text}"
    )
    return [
        {"role": "system", "content": system},  # generation instructions (not a 0-5 rubric)
        {"role": "user", "content": user},  # posting + resume skills for this session
    ]


def build_followup_messages(
    *,
    question_text: str,
    answer_text: str,
    evaluation: AnswerEvaluation,
    question_kind: QuestionKind | str,
) -> list[dict[str, str]]:
    """Build the turns for one follow-up question that probes the judge's gaps on this answer."""
    improvements = "; ".join(evaluation.improvements) if evaluation.improvements else "(none listed)"  # may be empty
    system = (  # one question only; schema is InterviewQuestion, not a list
        "You write one follow-up interview question that probes the gaps in the candidate's answer. "
        "Stay on the same topic as the original question. Do not repeat the original question. "
        f"Keep question_kind as {question_kind!r} unless the gap is clearly the other kind."
    )
    user = (  # original Q, the text answer, the 0-5 score, and the judge's improvement notes
        f"Original question:\n{question_text}\n\n"
        f"Candidate answer:\n{answer_text}\n\n"
        f"Judge score (0-5): {evaluation.score}\n"
        f"Judge improvements:\n{improvements}"
    )
    return [
        {"role": "system", "content": system},  # follow-up instructions
        {"role": "user", "content": user},  # evidence the follow-up should probe
    ]
