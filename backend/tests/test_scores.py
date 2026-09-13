"""API tests for weighted scores, ranking, comparison, and WeasyPrint PDFs.

Interview generate/evaluate use the existing fake provider (`_build_interview_provider` monkeypatch)
so this module never loads MiniLM, Whisper, or Ollama. PDF tests skip (never fail) when WeasyPrint
or cairo cannot be imported.
"""

from __future__ import annotations  # annotations

from uuid import UUID  # user ids

import pytest  # skip PDF when cairo is missing
from interview_fakes import (  # Phase 9-style fake provider; do not live-generate to get a Score
    FAKE_EVALUATION_OK,
    FAKE_EVALUATION_WEAK,
    FAKE_FOLLOW_UP,
    FakeInterviewBackend,
    bearer,
    create_user_with_tokens,
    install_fake,
)
from ml.scoring import SIGNAL_COMMUNICATION  # omitted on text-only

from app.core.db import AsyncSessionLocal  # direct ORM writes (ATS / speech_metrics)
from app.models.answer import Answer  # attach speech_metrics before the last evaluate
from app.models.enums import ResumeStatus, UserRole  # insert helpers
from app.models.job import Job  # posting for ranking
from app.models.resume import Resume  # ATS
from app.services.pdf_report import weasyprint_available  # skip PDF tests without cairo
from app.workers.settings import run_burst_worker  # in-process ARQ drain


async def _insert_resume(user_id: UUID, *, ats_score: float = 70.0, skills: list[str] | None = None) -> UUID:
    """Insert a parsed resume with a chosen ATS so ranking tests can differ composites without spaCy."""
    async with AsyncSessionLocal() as session:
        resume = Resume(
            user_id=user_id,  # owner
            file_path="/tmp/phase13-fake.pdf",  # never opened
            original_filename="resume.pdf",  # display
            status=ResumeStatus.PARSED,  # POST /interviews requires parsed
            parsed_data={
                "sections": {"skills": "Python"},  # unused by scoring
                "skills": skills or ["Python"],  # generate prompt
                "email": "jane@example.com",  # unused
                "phone": None,  # unused
                "extractor_used": "pymupdf",  # unused
                "ats_breakdown": {"section_points": 20, "contact_points": 10, "skill_points": 20, "length_points": 20},
            },
            ats_score=ats_score,  # resume_score signal
        )
        session.add(resume)  # insert
        await session.commit()  # persist
        return resume.id  # UUID


async def _insert_posting(recruiter_id: UUID) -> UUID:
    """Insert a posting the recruiter owns; interviews read title, ranking keys off job_id."""
    async with AsyncSessionLocal() as session:
        job = Job(
            recruiter_id=recruiter_id,  # owner
            title="Backend engineer",  # PDF cover
            description="Python APIs",  # unused by scoring
            required_skills="Python",  # unused by scoring
            is_active=True,  # POST /interviews 409s if inactive
        )
        session.add(job)  # insert
        await session.commit()  # persist
        return job.id  # UUID


async def _complete_session(
    client,
    monkeypatch: pytest.MonkeyPatch,
    *,
    resume_id: UUID,
    token: str,
    job_id: UUID | None = None,
    evaluation: dict | None = None,
    questions: list[dict[str, str]] | None = None,
) -> str:
    """Start + fake-generate + submit every question with a passing score so the session completes."""
    backend = FakeInterviewBackend(
        questions=questions
        or [{"question_text": "What is a Python list?", "question_kind": "technical"}],  # one Q → one evaluate
        evaluation=evaluation or FAKE_EVALUATION_OK,  # score 4 → no follow-up
    )
    install_fake(monkeypatch, backend)  # never hit Ollama
    body: dict[str, str] = {"resume_id": str(resume_id)}  # required parsed resume
    if job_id is not None:
        body["job_id"] = str(job_id)  # posting-targeted; ranking only sees these
    created = await client.post("/interviews", json=body, headers=bearer(token))
    assert created.status_code == 201, created.text  # start
    session_id = created.json()["session_id"]  # poll target
    await run_burst_worker()  # generate
    session_body = (await client.get(f"/interviews/{session_id}", headers=bearer(token))).json()
    for answer in session_body["answers"]:
        submitted = await client.post(
            f"/interviews/{session_id}/answers/{answer['id']}",
            json={"answer_text": "A mutable ordered sequence of objects."},  # min_length 1
            headers=bearer(token),
        )
        assert submitted.status_code == 200, submitted.text  # enqueue evaluate
        await run_burst_worker()  # evaluate (+ maybe complete)
    final = (await client.get(f"/interviews/{session_id}", headers=bearer(token))).json()
    assert final["status"] == "completed"  # Score row should exist now
    return session_id  # UUID string


async def test_completed_session_writes_score_text_only_omits_communication(client, redis_pool, monkeypatch):
    """Completing a text-only session upserts Score; communication is omitted, not stored as 0."""
    token, user_id = await create_user_with_tokens("sc-complete@example.com", "StrongPass123", UserRole.CANDIDATE)
    resume_id = await _insert_resume(user_id, ats_score=70.0)  # ATS 70
    session_id = await _complete_session(client, monkeypatch, resume_id=resume_id, token=token)

    scored = await client.get(f"/scores/{session_id}", headers=bearer(token))
    assert scored.status_code == 200, scored.text  # owner
    body = scored.json()
    assert body["session_id"] == session_id  # snake_case
    assert body["resume_score"] == pytest.approx(70.0)  # ATS
    assert body["technical_score"] == pytest.approx(80.0)  # 4 * 20
    assert body["communication_score"] is None  # text-only
    assert body["behavioral_score"] is None  # no behavioral question
    assert body["composite_score"] is not None  # weighted sum
    assert SIGNAL_COMMUNICATION in body["attribution"]["omitted"]  # reconstructable
    assert SIGNAL_COMMUNICATION not in body["attribution"]["signals"]  # not a fake 0
    contrib = sum(item["contribution"] for item in body["attribution"]["signals"].values())  # Article 86
    assert body["composite_score"] == pytest.approx(contrib)  # reconstruct


async def test_in_progress_session_has_no_score(client, redis_pool, monkeypatch):
    """A follow-up keeps the session in_progress; no composite is written yet."""
    backend = FakeInterviewBackend(
        questions=[{"question_text": "What is a Python list?", "question_kind": "technical"}],  # one original
        evaluation=FAKE_EVALUATION_WEAK,  # score 1 → follow-up
        follow_up=FAKE_FOLLOW_UP,  # appended
    )
    install_fake(monkeypatch, backend)  # fake judge
    token, user_id = await create_user_with_tokens("sc-open@example.com", "StrongPass123", UserRole.CANDIDATE)
    resume_id = await _insert_resume(user_id)  # parsed
    created = await client.post("/interviews", json={"resume_id": str(resume_id)}, headers=bearer(token))
    await run_burst_worker()  # generate
    session_id = created.json()["session_id"]  # id
    answer_id = (await client.get(f"/interviews/{session_id}", headers=bearer(token))).json()["answers"][0]["id"]
    await client.post(
        f"/interviews/{session_id}/answers/{answer_id}",
        json={"answer_text": "I don't know."},  # weak
        headers=bearer(token),
    )
    await run_burst_worker()  # evaluate + follow-up
    session_body = (await client.get(f"/interviews/{session_id}", headers=bearer(token))).json()
    assert session_body["status"] == "in_progress"  # still open
    missing = await client.get(f"/scores/{session_id}", headers=bearer(token))
    assert missing.status_code == 404  # no composite yet


async def test_score_get_is_owner_only(client, redis_pool, monkeypatch):
    """Another candidate polling someone else's session id gets 404, not 403."""
    owner, owner_id = await create_user_with_tokens("sc-own@example.com", "StrongPass123", UserRole.CANDIDATE)
    other, _ = await create_user_with_tokens("sc-other@example.com", "StrongPass123", UserRole.CANDIDATE)
    resume_id = await _insert_resume(owner_id)  # owner resume
    session_id = await _complete_session(client, monkeypatch, resume_id=resume_id, token=owner)
    hidden = await client.get(f"/scores/{session_id}", headers=bearer(other))
    assert hidden.status_code == 404  # not 403


async def test_recruiter_cannot_read_practice_score(client, redis_pool, monkeypatch):
    """Practice sessions (job_id null) are 404 for recruiters even when a Score exists."""
    recruiter, _ = await create_user_with_tokens("sc-rec@example.com", "StrongPass123", UserRole.RECRUITER)
    token, user_id = await create_user_with_tokens("sc-prac@example.com", "StrongPass123", UserRole.CANDIDATE)
    resume_id = await _insert_resume(user_id)  # parsed
    session_id = await _complete_session(client, monkeypatch, resume_id=resume_id, token=token)
    hidden = await client.get(f"/scores/{session_id}", headers=bearer(recruiter))
    assert hidden.status_code == 404  # practice is candidate-only


async def test_recruiter_ranking_and_compare(client, redis_pool, monkeypatch):
    """Two completed sessions on one posting rank by composite; compare returns both; other recruiter 404s."""
    recruiter_token, recruiter_id = await create_user_with_tokens(
        "sc-rank-r@example.com", "StrongPass123", UserRole.RECRUITER
    )
    other_rec, _ = await create_user_with_tokens("sc-rank-r2@example.com", "StrongPass123", UserRole.RECRUITER)
    posting_id = await _insert_posting(recruiter_id)  # owned
    cand_a, id_a = await create_user_with_tokens("sc-rank-a@example.com", "StrongPass123", UserRole.CANDIDATE)
    cand_b, id_b = await create_user_with_tokens("sc-rank-b@example.com", "StrongPass123", UserRole.CANDIDATE)
    resume_a = await _insert_resume(id_a, ats_score=70.0)  # lower ATS
    resume_b = await _insert_resume(id_b, ats_score=90.0)  # higher ATS
    session_a = await _complete_session(client, monkeypatch, resume_id=resume_a, token=cand_a, job_id=posting_id)
    session_b = await _complete_session(client, monkeypatch, resume_id=resume_b, token=cand_b, job_id=posting_id)

    ranked = await client.get(f"/scores/rankings?posting_id={posting_id}", headers=bearer(recruiter_token))
    assert ranked.status_code == 200, ranked.text  # owner
    rows = ranked.json()["sessions"]
    assert [row["session_id"] for row in rows] == [session_b, session_a]  # 90 ATS beats 70 with the same judge
    assert rows[0]["rank"] == 1  # 1-based
    assert rows[0]["candidate_email"] == "sc-rank-b@example.com"  # identifiable

    other_rank = await client.get(f"/scores/rankings?posting_id={posting_id}", headers=bearer(other_rec))
    assert other_rank.status_code == 404  # not 403

    cand_rank = await client.get(f"/scores/rankings?posting_id={posting_id}", headers=bearer(cand_a))
    assert cand_rank.status_code == 403  # require_recruiter

    recruiter_get = await client.get(f"/scores/{session_a}", headers=bearer(recruiter_token))
    assert recruiter_get.status_code == 200  # posting-owned session

    compared = await client.get(
        f"/scores/compare?session_ids={session_a}&session_ids={session_b}",
        headers=bearer(recruiter_token),
    )
    assert compared.status_code == 200, compared.text  # owner
    assert [row["session_id"] for row in compared.json()["sessions"]] == [session_a, session_b]  # request order

    foreign = await client.get(
        f"/scores/compare?session_ids={session_a}&session_ids={session_b}",
        headers=bearer(other_rec),
    )
    assert foreign.status_code == 404  # neither session is on a posting they own


async def test_communication_score_from_existing_speech_metrics(client, redis_pool, monkeypatch):
    """If speech_metrics already sit on the answer, completing the session includes communication_score."""
    backend = FakeInterviewBackend(
        questions=[{"question_text": "What is a Python list?", "question_kind": "technical"}],  # one Q
        evaluation=FAKE_EVALUATION_OK,  # complete
    )
    install_fake(monkeypatch, backend)  # fake
    token, user_id = await create_user_with_tokens("sc-speech@example.com", "StrongPass123", UserRole.CANDIDATE)
    resume_id = await _insert_resume(user_id)  # parsed
    created = await client.post("/interviews", json={"resume_id": str(resume_id)}, headers=bearer(token))
    await run_burst_worker()  # generate
    session_id = created.json()["session_id"]  # id
    answer_id = (await client.get(f"/interviews/{session_id}", headers=bearer(token))).json()["answers"][0]["id"]
    arm = {
        "speech_rate_wpm": 140.0,  # plateau
        "articulation_rate_wpm": 160.0,  # unused
        "mean_pause_duration_s": 0.4,  # unused
        "pause_ratio": 0.15,  # full marks
        "filler_rate": 0.02,  # full marks
        "filler_count": 1,  # unused
        "word_count": 40,  # unused
        "total_duration_s": 20.0,  # unused
        "speaking_duration_s": 17.0,  # unused
        "pause_duration_s": 3.0,  # unused
        "pause_count": 5,  # unused
    }
    async with AsyncSessionLocal() as session:
        answer = await session.get(Answer, UUID(answer_id))  # generated row
        assert answer is not None  # generate wrote it
        answer.speech_metrics = {
            "words": [],  # unused
            "language": "en",  # unused
            "duration_s": 20.0,  # unused
            "fluency_transcript": arm,  # both arms
            "fluency_acoustic": arm,  # equal, not a winner
            "prosody": {
                "pitch_mean_hz": 140.0,  # Hz
                "pitch_std_hz": 10.0,  # Hz
                "intensity_mean_db": 55.0,  # dB
                "intensity_std_db": 4.0,  # dB
            },
            "vad": {"speech_segments": [], "pauses": []},  # unused
        }
        await session.commit()  # evaluate will read this
    await client.post(
        f"/interviews/{session_id}/answers/{answer_id}",
        json={"answer_text": "A mutable ordered sequence."},  # submit
        headers=bearer(token),
    )
    await run_burst_worker()  # evaluate + score
    body = (await client.get(f"/scores/{session_id}", headers=bearer(token))).json()
    assert body["communication_score"] is not None  # mapped from speech_metrics
    assert body["communication_score"] > 90.0  # plateau WPM + low pause + low filler
    assert SIGNAL_COMMUNICATION not in body["attribution"]["omitted"]  # kept
    assert SIGNAL_COMMUNICATION in body["attribution"]["signals"]  # weighted


@pytest.mark.skipif(not weasyprint_available(), reason="WeasyPrint/cairo missing — skip, never fail")
async def test_report_pdf_owner_and_404(client, redis_pool, monkeypatch):
    """Completed session PDF starts with %PDF-; another user gets 404. Skips if cairo is missing."""
    token, user_id = await create_user_with_tokens("sc-pdf@example.com", "StrongPass123", UserRole.CANDIDATE)
    other, _ = await create_user_with_tokens("sc-pdf-other@example.com", "StrongPass123", UserRole.CANDIDATE)
    resume_id = await _insert_resume(user_id)  # parsed
    session_id = await _complete_session(client, monkeypatch, resume_id=resume_id, token=token)

    pdf = await client.get(f"/reports/{session_id}", headers=bearer(token))
    assert pdf.status_code == 200, pdf.text  # owner
    assert pdf.headers["content-type"].startswith("application/pdf")  # not JSON
    assert pdf.content[:5] == b"%PDF-"  # WeasyPrint magic
    assert len(pdf.content) > 500  # a real report, not an empty wrapper

    hidden = await client.get(f"/reports/{session_id}", headers=bearer(other))
    assert hidden.status_code == 404  # not 403

    missing = await client.get("/reports/00000000-0000-0000-0000-000000000099", headers=bearer(token))
    assert missing.status_code == 404  # unknown id
