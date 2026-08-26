"""Integration tests for interview start/generate/submit/evaluate against live Docker Postgres and Redis.

LLM HTTP is monkeypatched via `app.workers.tasks._build_interview_provider` so these tests never load
MiniLM or hit live Ollama. The one live generate+evaluate smoke at the bottom skips (never fails)
when the daemon is down, matching `test_ml_llm.py`.
"""

from __future__ import annotations  # FakeInterviewBackend forward refs

import json  # fake backend returns JSON strings complete_json will parse
from typing import Any  # evaluation dict in fake payloads
from uuid import UUID  # user ids returned by the register helper

import httpx  # 2s tags probe for the live smoke
import pytest  # skip
from ml.llm import LLMProvider, config_from_settings  # fake wraps LLMProvider; live smoke reads Settings

from app.auth import service  # register_user/issue_token_pair, used to mint tokens without hitting rate limits
from app.core.config import Settings, get_settings  # Settings for tokens; live smoke reads LLM_* fields
from app.core.db import AsyncSessionLocal  # session factory identical to the app's DI
from app.models.enums import ResumeStatus, UserRole  # parsed vs uploaded resumes; candidate vs recruiter
from app.models.job import Job  # optional posting inserted directly (no embedding needed for interviews)
from app.models.resume import Resume  # parsed/uploaded rows inserted directly so tests never load MiniLM
from app.workers.settings import run_burst_worker  # in-process ARQ drain used after enqueue

settings = get_settings()  # cached; tests share the process Settings with the app

# Default generate payload: two questions so GET session has a stable shape without a live model.
_FAKE_QUESTIONS = [
    {"question_text": "What is a Python list?", "question_kind": "technical"},
    {"question_text": "Tell me about a time you resolved a team conflict.", "question_kind": "behavioral"},
]
# Default judge payload: score 4 so follow-up does not fire unless a test overrides it.
_FAKE_EVALUATION_OK = {
    "score": 4,
    "rationale": "Covers the core idea with a clear definition.",
    "strengths": ["correct definition"],
    "improvements": ["add a concrete example"],
}
# Weak judge payload: score 1 so should_follow_up is True on an original question.
_FAKE_EVALUATION_WEAK = {
    "score": 1,
    "rationale": "Does not address the question.",
    "strengths": [],
    "improvements": ["define the data structure and give an example"],
}
# Follow-up question the fake returns when evaluate also calls complete_json(InterviewQuestion).
_FAKE_FOLLOW_UP = {
    "question_text": "Can you give a concrete example of using a list versus a tuple?",
    "question_kind": "technical",
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
        self.questions = questions if questions is not None else list(_FAKE_QUESTIONS)  # GeneratedQuestions.questions
        self.evaluation = evaluation if evaluation is not None else dict(_FAKE_EVALUATION_OK)  # AnswerEvaluation
        self.follow_up = follow_up if follow_up is not None else dict(_FAKE_FOLLOW_UP)  # InterviewQuestion
        self.raw_by_title = raw_by_title or {}  # optional invalid JSON per schema title (LLMJSONError path)
        self.titles_called: list[str] = []  # order of complete_json schemas this backend saw
        self.last_messages: list[dict[str, str]] | None = None  # last generate() messages, for prompt assertions

    def generate(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.0,
        json_schema: dict[str, Any] | None = None,
    ) -> str:
        del temperature  # fake is deterministic
        title = (json_schema or {}).get("title") or ""  # Pydantic v2 uses the class name
        self.titles_called.append(title)  # generate then evaluate then maybe follow-up
        self.last_messages = messages  # includes the JSON-contract system turn prepended by complete_json
        if title in self.raw_by_title:
            return self.raw_by_title[title]  # not valid JSON -> LLMJSONError -> async job failed
        if title == "GeneratedQuestions":
            return json.dumps({"questions": self.questions})  # 1-6 InterviewQuestion items
        if title == "AnswerEvaluation":
            return json.dumps(self.evaluation)  # score 0-5 + rationale + lists
        if title == "InterviewQuestion":
            return json.dumps(self.follow_up)  # single follow-up question
        raise AssertionError(f"unexpected json_schema title {title!r}")  # worker used an unexpected response_model

    def close(self) -> None:
        return None  # production backends close an owned httpx.Client; the fake owns nothing


def _install_fake(monkeypatch: pytest.MonkeyPatch, backend: FakeInterviewBackend) -> FakeInterviewBackend:
    """Point the worker's provider factory at this fake so burst workers never open HTTP."""
    monkeypatch.setattr(
        "app.workers.tasks._build_interview_provider",
        lambda: LLMProvider(backend),  # same facade the product uses; complete_json still enforces Pydantic
    )
    return backend


async def _create_user_with_tokens(email: str, password: str, role: UserRole) -> tuple[str, UUID]:
    """Register a user via the service layer and return (access_token, user_id)."""
    async with AsyncSessionLocal() as session:
        user = await service.register_user(
            session, email=email, password=password, full_name="Interview Tester", role=role
        )
        access_token, _ = await service.issue_token_pair(session, user=user, settings=settings)
        await session.commit()
        return access_token, user.id


def _bearer(access_token: str) -> dict[str, str]:
    """Build the Authorization header the interview routes expect."""
    return {"Authorization": f"Bearer {access_token}"}


async def _insert_resume(user_id: UUID, *, parsed: bool, skills: list[str] | None = None) -> UUID:
    """Insert a resume row directly so interview tests do not run spaCy/SBERT."""
    async with AsyncSessionLocal() as session:
        resume = Resume(
            user_id=user_id,
            file_path="/tmp/phase9-fake.pdf",  # never opened; generate reads parsed_data.skills only
            original_filename="resume.pdf",
            status=ResumeStatus.PARSED if parsed else ResumeStatus.UPLOADED,
            parsed_data=(
                {
                    "sections": {"skills": "Python, Docker"},
                    "skills": skills or ["Python", "Docker"],
                    "email": "jane@example.com",
                    "phone": None,
                    "extractor_used": "pymupdf",
                    "ats_breakdown": {},
                }
                if parsed
                else None
            ),
            ats_score=70.0 if parsed else None,
        )
        session.add(resume)
        await session.commit()
        return resume.id


async def _insert_posting(
    recruiter_id: UUID,
    *,
    title: str,
    description: str,
    required_skills: str,
    is_active: bool = True,
) -> UUID:
    """Insert a posting row directly; interviews read title/description/skills, not embeddings."""
    async with AsyncSessionLocal() as session:
        job = Job(
            recruiter_id=recruiter_id,
            title=title,
            description=description,
            required_skills=required_skills,
            is_active=is_active,
        )
        session.add(job)
        await session.commit()
        return job.id


async def test_start_enqueues_generate_and_returns_scheduled(client, redis_pool):
    """POST /interviews inserts a scheduled session and returns both ids without running the worker."""
    token, user_id = await _create_user_with_tokens("iv-queued@example.com", "StrongPass123", UserRole.CANDIDATE)
    resume_id = await _insert_resume(user_id, parsed=True)

    response = await client.post(
        "/interviews",
        json={"resume_id": str(resume_id)},
        headers=_bearer(token),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "scheduled"
    assert body["session_id"]
    assert body["async_job_id"]

    polled_session = await client.get(f"/interviews/{body['session_id']}", headers=_bearer(token))
    assert polled_session.status_code == 200
    assert polled_session.json()["status"] == "scheduled"  # worker has not run yet
    assert polled_session.json()["answers"] == []  # questions land when generate succeeds

    polled_job = await client.get(f"/jobs/{body['async_job_id']}", headers=_bearer(token))
    assert polled_job.status_code == 200
    assert polled_job.json()["job_type"] == "interview_generate"
    assert polled_job.json()["status"] == "queued"


async def test_worker_generates_questions_with_fake_provider(client, redis_pool, monkeypatch):
    """After a burst worker drains the queue, the session is in_progress with persisted questions."""
    backend = _install_fake(monkeypatch, FakeInterviewBackend())
    token, user_id = await _create_user_with_tokens("iv-gen-ok@example.com", "StrongPass123", UserRole.CANDIDATE)
    resume_id = await _insert_resume(user_id, parsed=True, skills=["Python", "Docker"])

    created = await client.post("/interviews", json={"resume_id": str(resume_id)}, headers=_bearer(token))
    assert created.status_code == 201
    session_id = created.json()["session_id"]
    job_id = created.json()["async_job_id"]

    await run_burst_worker()  # in-process ARQ worker; runs interview_generate then exits

    polled = await client.get(f"/interviews/{session_id}", headers=_bearer(token))
    assert polled.status_code == 200
    body = polled.json()
    assert body["status"] == "in_progress"
    assert body["resume_id"] == str(resume_id)
    assert body["started_at"] is not None
    assert len(body["answers"]) == 2
    assert body["answers"][0]["question_text"] == "What is a Python list?"
    assert body["answers"][0]["question_kind"] == "technical"
    assert body["answers"][0]["answer_text"] is None
    assert body["answers"][0]["is_follow_up"] is False
    assert body["answers"][1]["question_kind"] == "behavioral"
    assert "GeneratedQuestions" in backend.titles_called

    job = await client.get(f"/jobs/{job_id}", headers=_bearer(token))
    assert job.status_code == 200
    assert job.json()["status"] == "succeeded"
    assert job.json()["result"]["question_count"] == 2


async def test_submit_writes_evaluation_and_completes_when_no_follow_up(client, redis_pool, monkeypatch):
    """A passing score on the last unanswered question completes the session; no follow-up row."""
    backend = FakeInterviewBackend(
        questions=[{"question_text": "What is a Python list?", "question_kind": "technical"}],
        evaluation=_FAKE_EVALUATION_OK,  # score 4 -> should_follow_up is False
    )
    _install_fake(monkeypatch, backend)
    token, user_id = await _create_user_with_tokens("iv-eval-ok@example.com", "StrongPass123", UserRole.CANDIDATE)
    resume_id = await _insert_resume(user_id, parsed=True)

    created = await client.post("/interviews", json={"resume_id": str(resume_id)}, headers=_bearer(token))
    await run_burst_worker()
    session_id = created.json()["session_id"]
    session_body = (await client.get(f"/interviews/{session_id}", headers=_bearer(token))).json()
    answer_id = session_body["answers"][0]["id"]

    submitted = await client.post(
        f"/interviews/{session_id}/answers/{answer_id}",
        json={"answer_text": "A mutable ordered sequence of objects."},
        headers=_bearer(token),
    )
    assert submitted.status_code == 200
    eval_job_id = submitted.json()["async_job_id"]

    await run_burst_worker()  # interview_evaluate; no follow-up so session completes in this pass

    job = await client.get(f"/jobs/{eval_job_id}", headers=_bearer(token))
    assert job.json()["status"] == "succeeded"
    assert job.json()["result"]["score"] == 4
    assert job.json()["result"]["follow_up_appended"] is False

    final = (await client.get(f"/interviews/{session_id}", headers=_bearer(token))).json()
    assert final["status"] == "completed"
    assert final["completed_at"] is not None
    assert len(final["answers"]) == 1
    evaluation = final["answers"][0]["evaluation"]
    assert evaluation["score"] == 4
    assert evaluation["rationale"]
    assert final["answers"][0]["answer_text"] == "A mutable ordered sequence of objects."


async def test_follow_up_appended_when_score_at_or_below_2(client, redis_pool, monkeypatch):
    """Score <= 2 on an original question appends one follow-up; the session stays in_progress."""
    backend = FakeInterviewBackend(
        questions=[{"question_text": "What is a Python list?", "question_kind": "technical"}],
        evaluation=_FAKE_EVALUATION_WEAK,  # score 1
        follow_up=_FAKE_FOLLOW_UP,
    )
    _install_fake(monkeypatch, backend)
    token, user_id = await _create_user_with_tokens("iv-follow@example.com", "StrongPass123", UserRole.CANDIDATE)
    resume_id = await _insert_resume(user_id, parsed=True)

    created = await client.post("/interviews", json={"resume_id": str(resume_id)}, headers=_bearer(token))
    await run_burst_worker()
    session_id = created.json()["session_id"]
    answer_id = (await client.get(f"/interviews/{session_id}", headers=_bearer(token))).json()["answers"][0]["id"]

    await client.post(
        f"/interviews/{session_id}/answers/{answer_id}",
        json={"answer_text": "I don't know."},
        headers=_bearer(token),
    )
    await run_burst_worker()

    body = (await client.get(f"/interviews/{session_id}", headers=_bearer(token))).json()
    assert body["status"] == "in_progress"  # follow-up is still unanswered
    assert len(body["answers"]) == 2
    assert body["answers"][1]["is_follow_up"] is True
    assert body["answers"][1]["question_text"] == _FAKE_FOLLOW_UP["question_text"]
    assert body["answers"][1]["answer_text"] is None
    assert "InterviewQuestion" in backend.titles_called


async def test_follow_up_answer_does_not_chain_another_follow_up(client, redis_pool, monkeypatch):
    """Answering the follow-up with a weak score completes the session instead of chaining."""
    backend = FakeInterviewBackend(
        questions=[{"question_text": "What is a Python list?", "question_kind": "technical"}],
        evaluation=_FAKE_EVALUATION_WEAK,  # score 1 for both the original and the follow-up
        follow_up=_FAKE_FOLLOW_UP,
    )
    _install_fake(monkeypatch, backend)
    token, user_id = await _create_user_with_tokens("iv-nochain@example.com", "StrongPass123", UserRole.CANDIDATE)
    resume_id = await _insert_resume(user_id, parsed=True)

    created = await client.post("/interviews", json={"resume_id": str(resume_id)}, headers=_bearer(token))
    await run_burst_worker()
    session_id = created.json()["session_id"]
    first_id = (await client.get(f"/interviews/{session_id}", headers=_bearer(token))).json()["answers"][0]["id"]
    await client.post(
        f"/interviews/{session_id}/answers/{first_id}",
        json={"answer_text": "nope"},
        headers=_bearer(token),
    )
    await run_burst_worker()  # original -> follow-up appended

    follow_id = (await client.get(f"/interviews/{session_id}", headers=_bearer(token))).json()["answers"][1]["id"]
    await client.post(
        f"/interviews/{session_id}/answers/{follow_id}",
        json={"answer_text": "still nope"},
        headers=_bearer(token),
    )
    await run_burst_worker()  # follow-up scored 1 but is_follow_up=True so no third question

    body = (await client.get(f"/interviews/{session_id}", headers=_bearer(token))).json()
    assert len(body["answers"]) == 2  # no chain
    assert body["status"] == "completed"
    assert body["answers"][1]["evaluation"]["score"] == 1


async def test_session_get_is_owner_only(client, redis_pool):
    """A second candidate polling someone else's session id gets 404, not 403."""
    owner, owner_id = await _create_user_with_tokens("iv-owner@example.com", "StrongPass123", UserRole.CANDIDATE)
    other, _ = await _create_user_with_tokens("iv-other@example.com", "StrongPass123", UserRole.CANDIDATE)
    resume_id = await _insert_resume(owner_id, parsed=True)
    created = await client.post("/interviews", json={"resume_id": str(resume_id)}, headers=_bearer(owner))
    session_id = created.json()["session_id"]

    response = await client.get(f"/interviews/{session_id}", headers=_bearer(other))
    assert response.status_code == 404
    assert response.json()["detail"] == "session not found"


async def test_session_get_unknown_id_is_404(client, redis_pool):
    """GET /interviews/{id} for a UUID that was never inserted is 404."""
    token, _ = await _create_user_with_tokens("iv-missing@example.com", "StrongPass123", UserRole.CANDIDATE)
    response = await client.get(
        "/interviews/00000000-0000-0000-0000-000000000001",
        headers=_bearer(token),
    )
    assert response.status_code == 404


async def test_recruiter_cannot_start_session(client, redis_pool):
    """A recruiter account gets 403 from POST /interviews; only candidates may start."""
    token, _ = await _create_user_with_tokens("iv-recruiter@example.com", "StrongPass123", UserRole.RECRUITER)
    response = await client.post("/interviews", json={}, headers=_bearer(token))
    assert response.status_code == 403


async def test_start_requires_auth(client, redis_pool):
    """POST /interviews without a bearer token is 401."""
    response = await client.post("/interviews", json={})
    assert response.status_code == 401


async def test_owned_not_parsed_resume_is_409(client, redis_pool):
    """Explicit resume_id that exists and is owned but not yet parsed is 409, not 404."""
    token, user_id = await _create_user_with_tokens("iv-pending@example.com", "StrongPass123", UserRole.CANDIDATE)
    resume_id = await _insert_resume(user_id, parsed=False)
    response = await client.post(
        "/interviews",
        json={"resume_id": str(resume_id)},
        headers=_bearer(token),
    )
    assert response.status_code == 409


async def test_no_parsed_resume_is_404(client, redis_pool):
    """Omitting resume_id when the candidate has no parsed resume is 404."""
    token, _ = await _create_user_with_tokens("iv-none@example.com", "StrongPass123", UserRole.CANDIDATE)
    response = await client.post("/interviews", json={}, headers=_bearer(token))
    assert response.status_code == 404


async def test_foreign_resume_id_is_404(client, redis_pool):
    """resume_id belonging to another candidate is 404, not 403."""
    owner, owner_id = await _create_user_with_tokens("iv-res-owner@example.com", "StrongPass123", UserRole.CANDIDATE)
    other, _ = await _create_user_with_tokens("iv-res-other@example.com", "StrongPass123", UserRole.CANDIDATE)
    resume_id = await _insert_resume(owner_id, parsed=True)
    response = await client.post(
        "/interviews",
        json={"resume_id": str(resume_id)},
        headers=_bearer(other),
    )
    assert response.status_code == 404


async def test_inactive_posting_is_409(client, redis_pool):
    """An explicit job_id for an inactive posting is 409."""
    candidate, cand_id = await _create_user_with_tokens("iv-inact-c@example.com", "StrongPass123", UserRole.CANDIDATE)
    recruiter, rec_id = await _create_user_with_tokens("iv-inact-r@example.com", "StrongPass123", UserRole.RECRUITER)
    resume_id = await _insert_resume(cand_id, parsed=True)
    posting_id = await _insert_posting(
        rec_id,
        title="Closed role",
        description="No longer hiring.",
        required_skills="Python",
        is_active=False,
    )
    response = await client.post(
        "/interviews",
        json={"resume_id": str(resume_id), "job_id": str(posting_id)},
        headers=_bearer(candidate),
    )
    assert response.status_code == 409


async def test_generate_llm_error_marks_job_failed_and_session_abandoned(client, redis_pool, monkeypatch):
    """Invalid JSON from the model fails the async job with a short error; no free-text questions."""
    _install_fake(
        monkeypatch,
        FakeInterviewBackend(raw_by_title={"GeneratedQuestions": "this is not json"}),
    )
    token, user_id = await _create_user_with_tokens("iv-badjson@example.com", "StrongPass123", UserRole.CANDIDATE)
    resume_id = await _insert_resume(user_id, parsed=True)
    created = await client.post("/interviews", json={"resume_id": str(resume_id)}, headers=_bearer(token))
    job_id = created.json()["async_job_id"]
    session_id = created.json()["session_id"]

    await run_burst_worker()

    job = await client.get(f"/jobs/{job_id}", headers=_bearer(token))
    assert job.json()["status"] == "failed"
    assert job.json()["error"] is not None
    assert "LLMJSONError" in job.json()["error"]  # typed error, not a silent prose fallback

    session_body = (await client.get(f"/interviews/{session_id}", headers=_bearer(token))).json()
    assert session_body["status"] == "abandoned"
    assert session_body["answers"] == []


async def test_submit_is_owner_only_and_recruiter_forbidden(client, redis_pool, monkeypatch):
    """Submit on someone else's session is 404; a recruiter posting to any session is 403."""
    _install_fake(monkeypatch, FakeInterviewBackend(questions=[_FAKE_QUESTIONS[0]]))
    owner, owner_id = await _create_user_with_tokens("iv-sub-owner@example.com", "StrongPass123", UserRole.CANDIDATE)
    other, _ = await _create_user_with_tokens("iv-sub-other@example.com", "StrongPass123", UserRole.CANDIDATE)
    recruiter, _ = await _create_user_with_tokens("iv-sub-rec@example.com", "StrongPass123", UserRole.RECRUITER)
    resume_id = await _insert_resume(owner_id, parsed=True)
    created = await client.post("/interviews", json={"resume_id": str(resume_id)}, headers=_bearer(owner))
    await run_burst_worker()
    session_id = created.json()["session_id"]
    answer_id = (await client.get(f"/interviews/{session_id}", headers=_bearer(owner))).json()["answers"][0]["id"]

    other_submit = await client.post(
        f"/interviews/{session_id}/answers/{answer_id}",
        json={"answer_text": "stolen"},
        headers=_bearer(other),
    )
    assert other_submit.status_code == 404  # owner-only via 404, matching GET

    recruiter_submit = await client.post(
        f"/interviews/{session_id}/answers/{answer_id}",
        json={"answer_text": "recruiter"},
        headers=_bearer(recruiter),
    )
    assert recruiter_submit.status_code == 403  # require_candidate

    unauth = await client.post(
        f"/interviews/{session_id}/answers/{answer_id}",
        json={"answer_text": "anon"},
    )
    assert unauth.status_code == 401


async def test_start_with_posting_puts_title_in_generate_prompt(client, redis_pool, monkeypatch):
    """Optional job_id is persisted and the generate prompt includes the posting title."""
    backend = _install_fake(monkeypatch, FakeInterviewBackend())
    candidate, cand_id = await _create_user_with_tokens("iv-post-c@example.com", "StrongPass123", UserRole.CANDIDATE)
    recruiter, rec_id = await _create_user_with_tokens("iv-post-r@example.com", "StrongPass123", UserRole.RECRUITER)
    resume_id = await _insert_resume(cand_id, parsed=True)
    posting_id = await _insert_posting(
        rec_id,
        title="Platform Engineer",
        description="Operate Kubernetes clusters.",
        required_skills="Kubernetes, Python",
    )
    created = await client.post(
        "/interviews",
        json={"resume_id": str(resume_id), "job_id": str(posting_id)},
        headers=_bearer(candidate),
    )
    await run_burst_worker()
    session_id = created.json()["session_id"]
    body = (await client.get(f"/interviews/{session_id}", headers=_bearer(candidate))).json()
    assert body["job_id"] == str(posting_id)
    assert backend.last_messages is not None
    joined = " ".join(turn["content"] for turn in backend.last_messages)
    assert "Platform Engineer" in joined  # posting title reached complete_json
    assert "Kubernetes" in joined  # required skills reached complete_json


async def test_double_submit_is_409(client, redis_pool, monkeypatch):
    """A second POST on an already-answered question is 409."""
    _install_fake(
        monkeypatch,
        FakeInterviewBackend(questions=[{"question_text": "Q?", "question_kind": "technical"}]),
    )
    token, user_id = await _create_user_with_tokens("iv-dup@example.com", "StrongPass123", UserRole.CANDIDATE)
    resume_id = await _insert_resume(user_id, parsed=True)
    created = await client.post("/interviews", json={"resume_id": str(resume_id)}, headers=_bearer(token))
    await run_burst_worker()
    session_id = created.json()["session_id"]
    answer_id = (await client.get(f"/interviews/{session_id}", headers=_bearer(token))).json()["answers"][0]["id"]
    first = await client.post(
        f"/interviews/{session_id}/answers/{answer_id}",
        json={"answer_text": "first"},
        headers=_bearer(token),
    )
    assert first.status_code == 200
    second = await client.post(
        f"/interviews/{session_id}/answers/{answer_id}",
        json={"answer_text": "second"},
        headers=_bearer(token),
    )
    assert second.status_code == 409  # answer_text already set; worker may still be queued


async def test_live_ollama_generate_and_evaluate_smoke(client, redis_pool):
    """One real generate+evaluate through the worker; skips (never fails) if Ollama is down."""
    try:
        tags = httpx.get("http://127.0.0.1:11434/api/tags", timeout=2.0)  # cheap liveness probe
        tags.raise_for_status()
    except Exception as exc:
        pytest.skip(f"Ollama not reachable: {exc}")  # never fail the suite for a missing local daemon

    names = [item.get("name") for item in (tags.json().get("models") or []) if item.get("name")]
    if not names:
        pytest.skip("Ollama has no models pulled")  # do not ollama pull from pytest

    config = config_from_settings(Settings())  # honor .env via Settings, not os.environ
    if config.provider != "ollama":
        pytest.skip(f"LLM_PROVIDER={config.provider}; live smoke is Ollama-only")
    if config.ollama_model not in names:
        pytest.skip(
            f"OLLAMA_MODEL={config.ollama_model} is not pulled; library smoke covers tag fallback"
        )

    token, user_id = await _create_user_with_tokens("iv-live@example.com", "StrongPass123", UserRole.CANDIDATE)
    resume_id = await _insert_resume(user_id, parsed=True, skills=["Python"])
    created = await client.post("/interviews", json={"resume_id": str(resume_id)}, headers=_bearer(token))
    assert created.status_code == 201
    session_id = created.json()["session_id"]
    gen_job_id = created.json()["async_job_id"]

    await run_burst_worker()  # real Ollama complete_json(GeneratedQuestions)

    gen_job = (await client.get(f"/jobs/{gen_job_id}", headers=_bearer(token))).json()
    if gen_job["status"] == "failed":
        pytest.skip(f"live generate failed: {gen_job['error']}")  # weak local tag / VRAM; do not fail CI

    session_body = (await client.get(f"/interviews/{session_id}", headers=_bearer(token))).json()
    assert session_body["status"] == "in_progress"
    assert len(session_body["answers"]) >= 1
    answer_id = session_body["answers"][0]["id"]

    submitted = await client.post(
        f"/interviews/{session_id}/answers/{answer_id}",
        json={"answer_text": "A mutable ordered sequence of objects."},
        headers=_bearer(token),
    )
    assert submitted.status_code == 200
    eval_job_id = submitted.json()["async_job_id"]

    await run_burst_worker()  # real evaluate_answer (+ maybe follow-up)

    eval_job = (await client.get(f"/jobs/{eval_job_id}", headers=_bearer(token))).json()
    if eval_job["status"] == "failed":
        pytest.skip(f"live evaluate failed: {eval_job['error']}")  # JSON/schema flakiness: skip, never fail CI

    final = (await client.get(f"/interviews/{session_id}", headers=_bearer(token))).json()
    evaluation = final["answers"][0]["evaluation"]
    assert evaluation is not None
    assert 0 <= evaluation["score"] <= 5  # schema already enforces this
    assert evaluation["rationale"]  # non-empty justification from the live model
