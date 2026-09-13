"""Shared interview LLM fakes for tests. Not collected by pytest (name does not start with test_).

Phase 13 scoring tests monkeypatch `_build_interview_provider` the same way Phase 9 does so a Score
row can be written without MiniLM or live Ollama. `test_interviews.py` keeps its own copy so that
file is not rebuilt this phase.
"""

from __future__ import annotations  # FakeInterviewBackend forward refs

import json  # fake backend returns JSON strings complete_json will parse
from typing import Any  # evaluation dict in fake payloads
from uuid import UUID  # user ids returned by the register helper

import pytest  # MonkeyPatch type
from ml.llm import LLMProvider  # fake wraps LLMProvider

from app.auth import service  # register_user/issue_token_pair, used to mint tokens without hitting rate limits
from app.core.config import get_settings  # Settings for tokens
from app.core.db import AsyncSessionLocal  # session factory identical to the app's DI
from app.models.enums import UserRole  # candidate / recruiter

settings = get_settings()  # cached; tests share the process Settings with the app

# Default judge payload: score 4 so follow-up does not fire unless a test overrides it.
FAKE_EVALUATION_OK = {
    "score": 4,  # 0–5
    "rationale": "Covers the core idea with a clear definition.",  # judge prose
    "strengths": ["correct definition"],  # list
    "improvements": ["add a concrete example"],  # list; does not spawn a follow-up
}
# Weak judge payload: score 1 so should_follow_up is True on an original question.
FAKE_EVALUATION_WEAK = {
    "score": 1,  # triggers follow-up
    "rationale": "Does not address the question.",  # judge prose
    "strengths": [],  # empty
    "improvements": ["define the data structure and give an example"],  # coaching
}
# Follow-up question the fake returns when evaluate also calls complete_json(InterviewQuestion).
FAKE_FOLLOW_UP = {
    "question_text": "Can you give a concrete example of using a list versus a tuple?",  # probe
    "question_kind": "technical",  # keep kind
}


class FakeInterviewBackend:
    """Test double: JSON per schema title. Tests monkeypatch `_build_interview_provider` to wrap this."""

    name = "fake"  # not a real LLM_PROVIDER value; only injected via get_provider(backend=...)

    def __init__(
        self,
        *,
        questions: list[dict[str, str]] | None = None,
        evaluation: dict[str, Any] | None = None,
        follow_up: dict[str, str] | None = None,
        raw_by_title: dict[str, str] | None = None,
    ) -> None:
        self.questions = questions if questions is not None else [
            {"question_text": "What is a Python list?", "question_kind": "technical"},
        ]
        self.evaluation = evaluation if evaluation is not None else dict(FAKE_EVALUATION_OK)  # AnswerEvaluation
        self.follow_up = follow_up if follow_up is not None else dict(FAKE_FOLLOW_UP)  # InterviewQuestion
        self.raw_by_title = raw_by_title or {}  # optional invalid JSON per schema title
        self.titles_called: list[str] = []  # order of complete_json schemas this backend saw

    def generate(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.0,
        json_schema: dict[str, Any] | None = None,
    ) -> str:
        del temperature, messages  # fake is deterministic
        title = (json_schema or {}).get("title") or ""  # Pydantic v2 uses the class name
        self.titles_called.append(title)  # generate then evaluate then maybe follow-up
        if title in self.raw_by_title:
            return self.raw_by_title[title]  # not valid JSON -> LLMJSONError
        if title == "GeneratedQuestions":
            return json.dumps({"questions": self.questions})  # 1-6 InterviewQuestion items
        if title == "AnswerEvaluation":
            return json.dumps(self.evaluation)  # score 0-5 + rationale + lists
        if title == "InterviewQuestion":
            return json.dumps(self.follow_up)  # single follow-up question
        raise AssertionError(f"unexpected json_schema title {title!r}")  # unexpected response_model

    def close(self) -> None:
        return None  # production backends close an owned httpx.Client; the fake owns nothing


def install_fake(monkeypatch: pytest.MonkeyPatch, backend: FakeInterviewBackend) -> FakeInterviewBackend:
    """Point the worker's provider factory at this fake so burst workers never open HTTP."""
    monkeypatch.setattr(
        "app.workers.tasks._build_interview_provider",
        lambda: LLMProvider(backend),  # same facade the product uses; complete_json still enforces Pydantic
    )
    return backend  # caller may assert titles_called


async def create_user_with_tokens(email: str, password: str, role: UserRole) -> tuple[str, UUID]:
    """Register a user via the service layer and return (access_token, user_id)."""
    async with AsyncSessionLocal() as session:
        user = await service.register_user(
            session, email=email, password=password, full_name="Scoring Tester", role=role
        )
        access_token, _ = await service.issue_token_pair(session, user=user, settings=settings)
        await session.commit()
        return access_token, user.id


def bearer(access_token: str) -> dict[str, str]:
    """Build the Authorization header the score/report routes expect."""
    return {"Authorization": f"Bearer {access_token}"}
