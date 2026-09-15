"""API tests for candidate-only `GET /interviews` history (Phase 14 dashboard collection).

Does not live-generate. Direct ORM inserts cover empty/isolation/practice-vs-posting; one case uses
the shared interview fake + burst worker so a Score written by `interview_evaluate` shows up on the list.
"""

from __future__ import annotations  # postponed evaluation of annotations

from datetime import UTC, datetime, timedelta  # explicit created_at so newest-first is deterministic
from uuid import UUID  # user / resume / posting ids

import pytest  # monkeypatch type on the scored-list case
from interview_fakes import (  # Phase 13 fakes; do not load MiniLM or hit Ollama
    FAKE_EVALUATION_OK,
    FakeInterviewBackend,
    bearer,
    create_user_with_tokens,
    install_fake,
)

from app.core.db import AsyncSessionLocal  # same session factory the app uses
from app.models.enums import InterviewSessionStatus, ResumeStatus, UserRole  # insert helpers
from app.models.interview_session import InterviewSession  # history rows
from app.models.job import Job  # posting title on list items
from app.models.resume import Resume  # required FK on every session
from app.models.score import Score  # stored composite joined onto completed rows
from app.workers.settings import run_burst_worker  # drain generate+evaluate for the scored case


async def _insert_resume(user_id: UUID) -> UUID:
    """Insert a parsed resume so sessions can point at it without spaCy."""
    async with AsyncSessionLocal() as session:  # request-shaped session
        resume = Resume(
            user_id=user_id,  # owner
            file_path="/tmp/phase14-list.pdf",  # never opened
            original_filename="resume.pdf",  # display only
            status=ResumeStatus.PARSED,  # POST /interviews requires parsed; list does not care
            parsed_data={
                "skills": ["Python"],  # generate prompt if a test uses POST /interviews
                "sections": {},  # unused
                "email": None,  # unused
                "phone": None,  # unused
                "extractor_used": "pymupdf",  # unused
            },
            ats_score=70.0,  # unused by the list join
        )
        session.add(resume)  # stage
        await session.commit()  # persist
        return resume.id  # UUID


async def _insert_posting(recruiter_id: UUID, title: str = "Backend engineer") -> UUID:
    """Insert a posting so a session can carry posting_title."""
    async with AsyncSessionLocal() as session:  # request-shaped session
        job = Job(
            recruiter_id=recruiter_id,  # owner
            title=title,  # echoed on GET /interviews as posting_title
            description="Python APIs",  # unused
            required_skills="Python",  # unused by the list
            is_active=True,  # unused by the list
        )
        session.add(job)  # stage
        await session.commit()  # persist
        return job.id  # UUID


async def _insert_session(
    user_id: UUID,
    resume_id: UUID,
    *,
    job_id: UUID | None = None,
    status: InterviewSessionStatus = InterviewSessionStatus.SCHEDULED,
    created_at: datetime | None = None,
    composite_score: float | None = None,
) -> UUID:
    """Insert one interview_sessions row (and an optional Score) without running the LLM worker."""
    async with AsyncSessionLocal() as session:  # request-shaped session
        interview = InterviewSession(
            user_id=user_id,  # candidate owner
            resume_id=resume_id,  # required FK
            job_id=job_id,  # null = practice
            status=status,  # history includes scheduled / in_progress / completed / abandoned
            created_at=created_at or datetime.now(UTC),  # sort key
        )
        session.add(interview)  # stage so interview.id exists (UUID mixin default)
        await session.flush()  # id assigned before we optionally attach Score
        if composite_score is not None:
            session.add(
                Score(
                    session_id=interview.id,  # unique per session
                    composite_score=composite_score,  # list joins this
                    resume_score=70.0,  # unused by list payload
                    technical_score=80.0,  # unused by list payload
                    communication_score=None,  # omitted; list only exposes composite
                    behavioral_score=None,  # unused
                    attribution={"omitted": ["communication"], "signals": {}},  # unused by list
                )
            )
        await session.commit()  # persist
        return interview.id  # UUID


async def test_list_empty_for_new_candidate(client, redis_pool):
    """A candidate with no sessions gets an empty JSON array, not 404."""
    token, _ = await create_user_with_tokens("list-empty@example.com", "StrongPass123", UserRole.CANDIDATE)
    response = await client.get("/interviews", headers=bearer(token))  # collection, not /{id}
    assert response.status_code == 200, response.text  # empty is success
    assert response.json() == []  # dashboard empty state


async def test_list_is_candidate_only(client, redis_pool):
    """Recruiters must not dump sessions from GET /interviews; ranking is GET /scores/rankings."""
    token, _ = await create_user_with_tokens("list-rec@example.com", "StrongPass123", UserRole.RECRUITER)
    response = await client.get("/interviews", headers=bearer(token))  # require_candidate
    assert response.status_code == 403  # not a global dump
    unauth = await client.get("/interviews")  # no bearer
    assert unauth.status_code == 401  # same as other candidate writes


async def test_list_own_sessions_newest_first_practice_vs_posting(client, redis_pool):
    """Caller sees only their rows, newest created_at first; practice has null job_id/posting_title."""
    owner, owner_id = await create_user_with_tokens("list-own@example.com", "StrongPass123", UserRole.CANDIDATE)
    other, other_id = await create_user_with_tokens("list-other@example.com", "StrongPass123", UserRole.CANDIDATE)
    recruiter, rec_id = await create_user_with_tokens("list-post-r@example.com", "StrongPass123", UserRole.RECRUITER)
    owner_resume = await _insert_resume(owner_id)  # owner FK
    other_resume = await _insert_resume(other_id)  # other candidate's resume
    posting_id = await _insert_posting(rec_id, title="Staff Python")  # posting_title echo
    older = datetime.now(UTC) - timedelta(seconds=30)  # first insert, should sort second
    newer = datetime.now(UTC) - timedelta(seconds=5)  # second insert, should sort first
    practice_id = await _insert_session(
        owner_id,
        owner_resume,
        status=InterviewSessionStatus.ABANDONED,  # history includes abandoned
        created_at=older,  # older
    )
    posting_session_id = await _insert_session(
        owner_id,
        owner_resume,
        job_id=posting_id,  # posting-targeted
        status=InterviewSessionStatus.COMPLETED,  # scored
        created_at=newer,  # newer
        composite_score=88.5,  # stored Score join
    )
    await _insert_session(other_id, other_resume, created_at=datetime.now(UTC))  # must not leak

    response = await client.get("/interviews", headers=bearer(owner))  # owner history
    assert response.status_code == 200, response.text  # ok
    rows = response.json()  # list[InterviewSessionListItemOut]
    assert [row["id"] for row in rows] == [str(posting_session_id), str(practice_id)]  # newest first
    assert rows[0]["job_id"] == str(posting_id)  # posting session
    assert rows[0]["posting_title"] == "Staff Python"  # Job.title
    assert rows[0]["status"] == "completed"  # enum value
    assert rows[0]["composite_score"] == pytest.approx(88.5)  # stored, not recomputed
    assert rows[1]["job_id"] is None  # practice
    assert rows[1]["posting_title"] is None  # no posting
    assert rows[1]["status"] == "abandoned"  # still listed
    assert rows[1]["composite_score"] is None  # abandoned has no Score

    other_list = await client.get("/interviews", headers=bearer(other))  # isolation
    assert len(other_list.json()) == 1  # only the other candidate's row
    assert other_list.json()[0]["id"] != str(practice_id)  # not the owner's practice id


async def test_list_includes_score_written_by_evaluate(client, redis_pool, monkeypatch):
    """A session completed through the fake evaluate worker appears on GET /interviews with composite."""
    backend = FakeInterviewBackend(
        questions=[{"question_text": "What is a Python list?", "question_kind": "technical"}],  # one Q
        evaluation=FAKE_EVALUATION_OK,  # score 4 → no follow-up → completed
    )
    install_fake(monkeypatch, backend)  # never hit Ollama
    token, user_id = await create_user_with_tokens("list-eval@example.com", "StrongPass123", UserRole.CANDIDATE)
    resume_id = await _insert_resume(user_id)  # parsed
    created = await client.post("/interviews", json={"resume_id": str(resume_id)}, headers=bearer(token))
    assert created.status_code == 201, created.text  # start
    session_id = created.json()["session_id"]  # list target
    await run_burst_worker()  # generate
    answer_id = (await client.get(f"/interviews/{session_id}", headers=bearer(token))).json()["answers"][0]["id"]
    submitted = await client.post(
        f"/interviews/{session_id}/answers/{answer_id}",
        json={"answer_text": "A mutable ordered sequence of objects."},  # min_length 1
        headers=bearer(token),
    )
    assert submitted.status_code == 200, submitted.text  # enqueue evaluate
    await run_burst_worker()  # evaluate + Score upsert
    listed = await client.get("/interviews", headers=bearer(token))  # collection
    assert listed.status_code == 200, listed.text  # ok
    rows = listed.json()  # one session
    assert len(rows) == 1  # only this session
    assert rows[0]["id"] == session_id  # same UUID as POST
    assert rows[0]["status"] == "completed"  # evaluate flipped it
    assert rows[0]["job_id"] is None  # practice belongs on candidate history, not ranking
    assert rows[0]["composite_score"] is not None  # Score row joined
    assert rows[0]["composite_score"] > 0  # renormalized 0–100, not a fake 0
