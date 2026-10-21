"""API tests for weighted scores, ranking, comparison, and WeasyPrint PDFs (`scoring_v2`, four signals).

Every session is completed the way a candidate does it: audio upload -> fake transcribe -> fake judge.
The shared fakes in `interview_fakes` mean this module never loads MiniLM, Whisper, or Ollama. PDF tests
skip (never fail) when WeasyPrint or cairo cannot be imported.
"""

from __future__ import annotations  # annotations without quotes

from uuid import UUID  # user ids

import pytest  # skip PDF when cairo is missing
from interview_fakes import (  # one shared set of fakes and helpers
    FAKE_EVALUATION_OK,
    FAKE_EVALUATION_WEAK,
    FAKE_FOLLOW_UP,
    FakeInterviewBackend,
    bearer,
    create_user_with_tokens,
    insert_posting,
    insert_resume,
    install_fake,
    install_fake_speech,
    speak,
)
from ml.scoring import ALL_SIGNALS  # the four required signal names

from app.models.enums import UserRole  # candidate / recruiter
from app.services.pdf_report import weasyprint_available  # skip PDF tests without cairo
from app.workers.settings import run_burst_worker  # in-process ARQ drain

# Default weights are 20/30/25/15, normalized over their sum of 90.
_DENOMINATOR = 90.0


async def _complete_session(
    client,
    monkeypatch: pytest.MonkeyPatch,
    *,
    resume_id: UUID,
    token: str,
    job_id: UUID | None = None,
) -> str:
    """Start, fake-generate, then speak every question (score 4, no follow-up) so the session completes."""
    install_fake(monkeypatch, FakeInterviewBackend(evaluation=FAKE_EVALUATION_OK))  # technical + behavioral
    install_fake_speech(monkeypatch)  # fake transcript + dual fluency arms
    body: dict[str, str] = {"resume_id": str(resume_id)}  # required parsed resume
    if job_id is not None:
        body["job_id"] = str(job_id)  # posting-targeted; ranking only sees these
    created = await client.post("/interviews", json=body, headers=bearer(token))
    assert created.status_code == 201, created.text  # start
    session_id = created.json()["session_id"]  # poll target
    await run_burst_worker()  # generate
    session_body = (await client.get(f"/interviews/{session_id}", headers=bearer(token))).json()
    for answer in session_body["answers"]:
        uploaded = await speak(client, token, session_id, answer["id"])
        assert uploaded.status_code == 200, uploaded.text  # enqueue transcribe
        await run_burst_worker()  # transcribe, then the evaluate it enqueues (+ maybe complete)
    final = (await client.get(f"/interviews/{session_id}", headers=bearer(token))).json()
    assert final["status"] == "completed"  # Score row should exist now
    return session_id  # UUID string


async def test_completed_session_stores_all_four_signals_under_scoring_v2(client, redis_pool, monkeypatch):
    """A completed spoken session stores every signal, versioned scoring_v2, with the 20/30/25/15 weighted sum."""
    token, user_id = await create_user_with_tokens("sc-complete@example.com", "StrongPass123", UserRole.CANDIDATE)
    resume_id = await insert_resume(user_id, ats_score=70.0)  # ATS 70
    session_id = await _complete_session(client, monkeypatch, resume_id=resume_id, token=token)

    scored = await client.get(f"/scores/{session_id}", headers=bearer(token))
    assert scored.status_code == 200, scored.text  # owner
    body = scored.json()
    assert body["session_id"] == session_id  # snake_case
    assert body["resume_score"] == pytest.approx(70.0)  # ATS
    assert body["technical_score"] == pytest.approx(80.0)  # 4 * 20
    assert body["behavioral_score"] == pytest.approx(80.0)  # 4 * 20
    assert body["communication_score"] is not None  # never null, never a fake 0
    attribution = body["attribution"]
    assert attribution["formula_version"] == "scoring_v2"
    assert "omitted" not in attribution  # v2 never omits
    assert set(attribution["signals"]) == set(ALL_SIGNALS)  # all four listed
    assert attribution["weight_denominator"] == pytest.approx(_DENOMINATOR)
    expected = (
        20.0 * body["resume_score"]
        + 30.0 * body["technical_score"]
        + 25.0 * body["communication_score"]
        + 15.0 * body["behavioral_score"]
    ) / _DENOMINATOR  # 20/90, 30/90, 25/90, 15/90
    assert body["composite_score"] == pytest.approx(expected)
    contrib = sum(item["contribution"] for item in attribution["signals"].values())  # Article 86
    assert body["composite_score"] == pytest.approx(contrib)  # reconstructable

    again = await client.get(f"/scores/{session_id}", headers=bearer(token))
    assert again.json() == body  # GET reads the stored row; it never recomputes


async def test_in_progress_session_has_no_score(client, redis_pool, monkeypatch):
    """A weak answer appends a follow-up that still needs audio, so the session stays open with no composite."""
    install_fake(monkeypatch, FakeInterviewBackend(evaluation=FAKE_EVALUATION_WEAK, follow_up=FAKE_FOLLOW_UP))
    install_fake_speech(monkeypatch)
    token, user_id = await create_user_with_tokens("sc-open@example.com", "StrongPass123", UserRole.CANDIDATE)
    resume_id = await insert_resume(user_id)  # parsed
    created = await client.post("/interviews", json={"resume_id": str(resume_id)}, headers=bearer(token))
    await run_burst_worker()  # generate
    session_id = created.json()["session_id"]  # id
    answers = (await client.get(f"/interviews/{session_id}", headers=bearer(token))).json()["answers"]
    for answer in answers:  # answer both generated questions; both score weak and add a follow-up
        await speak(client, token, session_id, answer["id"])
        await run_burst_worker()
    session_body = (await client.get(f"/interviews/{session_id}", headers=bearer(token))).json()
    assert session_body["status"] == "in_progress"  # follow-ups are unanswered
    missing = await client.get(f"/scores/{session_id}", headers=bearer(token))
    assert missing.status_code == 404  # no composite yet


async def test_missing_resume_ats_keeps_session_open_and_fails_evaluate(client, redis_pool, monkeypatch):
    """No ATS means no resume signal: the evaluation is stored, the session stays open, and no Score is written."""
    install_fake(monkeypatch, FakeInterviewBackend(evaluation=FAKE_EVALUATION_OK))
    install_fake_speech(monkeypatch)
    token, user_id = await create_user_with_tokens("sc-noats@example.com", "StrongPass123", UserRole.CANDIDATE)
    resume_id = await insert_resume(user_id, ats_score=None)  # parsed but unscored
    created = await client.post("/interviews", json={"resume_id": str(resume_id)}, headers=bearer(token))
    await run_burst_worker()  # generate
    session_id = created.json()["session_id"]
    answers = (await client.get(f"/interviews/{session_id}", headers=bearer(token))).json()["answers"]
    last_transcribe = None
    for answer in answers:
        last_transcribe = (await speak(client, token, session_id, answer["id"])).json()["async_job_id"]
        await run_burst_worker()

    transcribe_job = (await client.get(f"/jobs/{last_transcribe}", headers=bearer(token))).json()
    eval_job_id = transcribe_job["result"]["evaluate_async_job_id"]
    eval_job = (await client.get(f"/jobs/{eval_job_id}", headers=bearer(token))).json()
    assert eval_job["status"] == "failed"
    assert "resume" in eval_job["error"]  # names the missing signal
    body = (await client.get(f"/interviews/{session_id}", headers=bearer(token))).json()
    assert body["status"] == "in_progress"  # not completed
    assert all(row["evaluation"] is not None for row in body["answers"])  # evaluations were still committed
    assert (await client.get(f"/scores/{session_id}", headers=bearer(token))).status_code == 404


async def test_score_get_is_owner_only(client, redis_pool, monkeypatch):
    """Another candidate polling someone else's session id gets 404, not 403."""
    owner, owner_id = await create_user_with_tokens("sc-own@example.com", "StrongPass123", UserRole.CANDIDATE)
    other, _ = await create_user_with_tokens("sc-other@example.com", "StrongPass123", UserRole.CANDIDATE)
    resume_id = await insert_resume(owner_id)  # owner resume
    session_id = await _complete_session(client, monkeypatch, resume_id=resume_id, token=owner)
    hidden = await client.get(f"/scores/{session_id}", headers=bearer(other))
    assert hidden.status_code == 404  # not 403


async def test_recruiter_cannot_read_practice_score(client, redis_pool, monkeypatch):
    """Practice sessions (job_id null) are 404 for recruiters even when a Score exists."""
    recruiter, _ = await create_user_with_tokens("sc-rec@example.com", "StrongPass123", UserRole.RECRUITER)
    token, user_id = await create_user_with_tokens("sc-prac@example.com", "StrongPass123", UserRole.CANDIDATE)
    resume_id = await insert_resume(user_id)  # parsed
    session_id = await _complete_session(client, monkeypatch, resume_id=resume_id, token=token)
    hidden = await client.get(f"/scores/{session_id}", headers=bearer(recruiter))
    assert hidden.status_code == 404  # practice is candidate-only


async def test_recruiter_ranking_and_compare(client, redis_pool, monkeypatch):
    """Two completed sessions on one posting rank by composite; compare returns both; other recruiter 404s."""
    recruiter_token, recruiter_id = await create_user_with_tokens(
        "sc-rank-r@example.com", "StrongPass123", UserRole.RECRUITER
    )
    other_rec, _ = await create_user_with_tokens("sc-rank-r2@example.com", "StrongPass123", UserRole.RECRUITER)
    posting_id = await insert_posting(recruiter_id, title="Backend engineer")  # owned
    cand_a, id_a = await create_user_with_tokens("sc-rank-a@example.com", "StrongPass123", UserRole.CANDIDATE)
    cand_b, id_b = await create_user_with_tokens("sc-rank-b@example.com", "StrongPass123", UserRole.CANDIDATE)
    resume_a = await insert_resume(id_a, ats_score=70.0)  # lower ATS
    resume_b = await insert_resume(id_b, ats_score=90.0)  # higher ATS
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


async def test_communication_score_comes_from_both_fluency_arms(client, redis_pool, monkeypatch):
    """The fake pipeline's plateau-WPM, low-pause, no-filler arms score communication well above 90."""
    token, user_id = await create_user_with_tokens("sc-speech@example.com", "StrongPass123", UserRole.CANDIDATE)
    resume_id = await insert_resume(user_id)  # parsed
    session_id = await _complete_session(client, monkeypatch, resume_id=resume_id, token=token)
    body = (await client.get(f"/scores/{session_id}", headers=bearer(token))).json()
    assert body["communication_score"] > 90.0  # plateau WPM + low pause ratio + zero fillers
    assert "communication" in body["attribution"]["signals"]  # weighted, not omitted


@pytest.mark.skipif(not weasyprint_available(), reason="WeasyPrint/cairo missing — skip, never fail")
async def test_report_pdf_owner_and_404(client, redis_pool, monkeypatch):
    """Completed session PDF starts with %PDF-; another user gets 404. Skips if cairo is missing."""
    token, user_id = await create_user_with_tokens("sc-pdf@example.com", "StrongPass123", UserRole.CANDIDATE)
    other, _ = await create_user_with_tokens("sc-pdf-other@example.com", "StrongPass123", UserRole.CANDIDATE)
    resume_id = await insert_resume(user_id)  # parsed
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
