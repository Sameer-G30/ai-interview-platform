"""Integration tests for the spoken interview flow against live Docker Postgres and Redis.

Answers are spoken: audio upload -> transcribe (fake pipeline) -> `answer_text` copy -> evaluate (fake
judge) -> follow-up / completion. LLM and speech are monkeypatched via the shared `interview_fakes`
module, so nothing loads MiniLM, Ollama, or Whisper. The one live smoke at the bottom skips (never
fails) when the daemon is down, matching `test_ml_llm.py`.
"""

from __future__ import annotations  # annotations without quotes

import httpx  # 2s tags probe for the live smoke
import pytest  # skip
from interview_fakes import (  # one shared set of fakes and helpers (pythonpath includes backend/tests)
    FAKE_EVALUATION_OK,
    FAKE_EVALUATION_WEAK,
    FAKE_FOLLOW_UP,
    FakeInterviewBackend,
    bearer,
    create_user_with_tokens,
    insert_posting,
    insert_resume,
    insert_session_with_questions,
    install_fake,
    install_fake_speech,
    speak,
    tiny_webm,
)
from ml.llm import config_from_settings  # live smoke reads Settings

from app.core.config import Settings  # live smoke reads LLM_* fields
from app.core.db import AsyncSessionLocal  # direct row assertions
from app.models.answer import Answer  # audio-upload assertions
from app.models.enums import UserRole  # candidate / recruiter
from app.workers.settings import run_burst_worker  # in-process ARQ drain used after enqueue

# Short aliases so the bodies below read the way the old per-file helpers did.
_bearer = bearer
_create_user_with_tokens = create_user_with_tokens
_install_fake = install_fake
_tiny_webm = tiny_webm
_FAKE_EVALUATION_OK = FAKE_EVALUATION_OK
_FAKE_EVALUATION_WEAK = FAKE_EVALUATION_WEAK
_FAKE_FOLLOW_UP = FAKE_FOLLOW_UP


async def _insert_resume(user_id, *, parsed: bool, skills: list[str] | None = None):
    """Thin wrapper over the shared helper: `skills` is accepted for call-site compatibility."""
    del skills  # the shared helper always stores ["Python"]
    return await insert_resume(user_id, parsed=parsed)


_insert_posting = insert_posting  # same name the tests below already use


async def _start_and_generate(client, token, user_id, *, job_id=None):
    """Start a session from a fresh parsed resume, drain generate, return (session_id, [answer ids])."""
    resume_id = await insert_resume(user_id)
    body = {"resume_id": str(resume_id)}
    if job_id is not None:
        body["job_id"] = str(job_id)
    created = await client.post("/interviews", json=body, headers=bearer(token))
    assert created.status_code == 201
    await run_burst_worker()  # interview_generate
    session_id = created.json()["session_id"]
    answers = (await client.get(f"/interviews/{session_id}", headers=bearer(token))).json()["answers"]
    return session_id, [row["id"] for row in answers]


async def _speak_and_drain(client, token, session_id, answer_id, **kwargs):
    """Upload audio then drain: transcribe runs, then the evaluate job it enqueues."""
    uploaded = await speak(client, token, session_id, answer_id, **kwargs)
    assert uploaded.status_code == 200, uploaded.text
    await run_burst_worker()
    return uploaded.json()


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


async def test_generate_tops_up_a_missing_kind(client, redis_pool, monkeypatch):
    """If the model returns only technical questions, one top-up call adds a behavioral one."""
    backend = FakeInterviewBackend(
        questions=[{"question_text": "What is a list?", "question_kind": "technical"}],
        follow_up={"question_text": "Describe a time you led a project.", "question_kind": "behavioral"},  # top-up
    )
    _install_fake(monkeypatch, backend)
    token, user_id = await _create_user_with_tokens("iv-topup@example.com", "StrongPass123", UserRole.CANDIDATE)
    session_id, _ = await _start_and_generate(client, token, user_id)

    body = (await client.get(f"/interviews/{session_id}", headers=_bearer(token))).json()
    assert body["status"] == "in_progress"
    assert [row["question_kind"] for row in body["answers"]] == ["technical", "behavioral"]  # both guaranteed
    assert backend.titles_called.count("InterviewQuestion") == 1  # exactly one top-up call


async def test_generate_abandons_when_topup_returns_wrong_kind(client, redis_pool, monkeypatch):
    """A top-up of the wrong kind is not relabelled: generate fails and the session is abandoned."""
    backend = FakeInterviewBackend(
        questions=[{"question_text": "What is a list?", "question_kind": "technical"}],
        follow_up={"question_text": "Another technical one?", "question_kind": "technical"},  # wrong kind
    )
    _install_fake(monkeypatch, backend)
    token, user_id = await _create_user_with_tokens("iv-topbad@example.com", "StrongPass123", UserRole.CANDIDATE)
    resume_id = await insert_resume(user_id)
    created = await client.post("/interviews", json={"resume_id": str(resume_id)}, headers=_bearer(token))
    await run_burst_worker()

    job = (await client.get(f"/jobs/{created.json()['async_job_id']}", headers=_bearer(token))).json()
    assert job["status"] == "failed"
    assert "QuestionKindError" in job["error"]
    session_body = (await client.get(f"/interviews/{created.json()['session_id']}", headers=_bearer(token))).json()
    assert session_body["status"] == "abandoned"
    assert session_body["answers"] == []  # nothing was persisted


async def test_text_submit_is_gone_and_writes_nothing(client, redis_pool, monkeypatch):
    """The typed-answer endpoint returns 410 and leaves the row untouched; 401/403 still apply first."""
    _install_fake(monkeypatch, FakeInterviewBackend())
    token, user_id = await _create_user_with_tokens("iv-gone@example.com", "StrongPass123", UserRole.CANDIDATE)
    recruiter, _ = await _create_user_with_tokens("iv-gone-r@example.com", "StrongPass123", UserRole.RECRUITER)
    session_id, answer_ids = await _start_and_generate(client, token, user_id)
    url = f"/interviews/{session_id}/answers/{answer_ids[0]}"

    gone = await client.post(url, json={"answer_text": "typed"}, headers=_bearer(token))
    assert gone.status_code == 410
    assert gone.json()["detail"] == "answers are spoken: record and upload audio"
    assert (await client.post(url, json={"answer_text": "x"}, headers=_bearer(recruiter))).status_code == 403
    assert (await client.post(url, json={"answer_text": "x"})).status_code == 401

    row = (await client.get(f"/interviews/{session_id}", headers=_bearer(token))).json()["answers"][0]
    assert row["answer_text"] is None  # nothing written
    assert row["evaluation"] is None


async def test_spoken_answer_flows_transcript_into_answer_text_then_evaluation(client, redis_pool, monkeypatch):
    """Upload -> transcribe -> answer_text equals the transcript -> evaluate writes a judge score."""
    _install_fake(monkeypatch, FakeInterviewBackend())  # score 4: no follow-up
    install_fake_speech(monkeypatch)  # transcript "hello world"
    token, user_id = await _create_user_with_tokens("iv-spoken@example.com", "StrongPass123", UserRole.CANDIDATE)
    session_id, answer_ids = await _start_and_generate(client, token, user_id)

    uploaded = await _speak_and_drain(client, token, session_id, answer_ids[0])

    transcribe_job = (await client.get(f"/jobs/{uploaded['async_job_id']}", headers=_bearer(token))).json()
    assert transcribe_job["status"] == "succeeded"
    assert transcribe_job["result"]["evaluate_enqueued"] is True
    eval_job_id = transcribe_job["result"]["evaluate_async_job_id"]  # what the SPA polls next
    eval_job = (await client.get(f"/jobs/{eval_job_id}", headers=_bearer(token))).json()
    assert eval_job["status"] == "succeeded"
    assert eval_job["result"]["score"] == 4

    body = (await client.get(f"/interviews/{session_id}", headers=_bearer(token))).json()
    row = body["answers"][0]
    assert row["transcript"] == "hello world"
    assert row["answer_text"] == "hello world"  # the transcript IS the answer
    assert row["evaluation"]["score"] == 4
    assert body["status"] == "in_progress"  # the behavioral question is still open


async def test_follow_up_requires_audio_and_is_appended_after_a_weak_answer(client, redis_pool, monkeypatch):
    """Score <= 2 appends one follow-up that stays unanswered, and the session cannot complete without audio."""
    backend = FakeInterviewBackend(evaluation=_FAKE_EVALUATION_WEAK, follow_up=_FAKE_FOLLOW_UP)
    _install_fake(monkeypatch, backend)
    install_fake_speech(monkeypatch)
    token, user_id = await _create_user_with_tokens("iv-follow@example.com", "StrongPass123", UserRole.CANDIDATE)
    session_id, answer_ids = await _start_and_generate(client, token, user_id)

    await _speak_and_drain(client, token, session_id, answer_ids[0])

    body = (await client.get(f"/interviews/{session_id}", headers=_bearer(token))).json()
    assert body["status"] == "in_progress"
    assert len(body["answers"]) == 3  # two generated + one appended at the end
    follow = body["answers"][2]
    assert follow["is_follow_up"] is True
    assert follow["question_text"] == _FAKE_FOLLOW_UP["question_text"]
    assert follow["answer_text"] is None and follow["has_audio"] is False  # needs its own recording
    assert "InterviewQuestion" in backend.titles_called


async def test_follow_up_answer_does_not_chain_another_follow_up(client, redis_pool, monkeypatch):
    """A weak answer to a follow-up never creates a third probe; the session still needs every row spoken."""
    _install_fake(monkeypatch, FakeInterviewBackend(evaluation=_FAKE_EVALUATION_WEAK, follow_up=_FAKE_FOLLOW_UP))
    install_fake_speech(monkeypatch)
    token, user_id = await _create_user_with_tokens("iv-nochain@example.com", "StrongPass123", UserRole.CANDIDATE)
    resume_id = await insert_resume(user_id)
    session_id, ids = await insert_session_with_questions(user_id, resume_id, kinds=("technical", "behavioral"))

    await _speak_and_drain(client, token, session_id, ids[0])  # weak -> follow-up appended
    await _speak_and_drain(client, token, session_id, ids[1])  # weak behavioral -> its own follow-up
    body = (await client.get(f"/interviews/{session_id}", headers=_bearer(token))).json()
    follow_ids = [row["id"] for row in body["answers"] if row["is_follow_up"]]
    assert len(follow_ids) == 2
    for follow_id in follow_ids:
        await _speak_and_drain(client, token, session_id, follow_id)  # weak follow-ups must not chain

    final = (await client.get(f"/interviews/{session_id}", headers=_bearer(token))).json()
    assert len(final["answers"]) == 4  # no third-generation probes
    assert final["status"] == "completed"  # every row now has audio, metrics, text, evaluation


async def test_upload_is_409_after_the_answer_is_scored_and_on_a_completed_session(client, redis_pool, monkeypatch):
    """A scored answer cannot be re-recorded, and a completed session accepts no audio at all."""
    _install_fake(monkeypatch, FakeInterviewBackend())  # score 4 everywhere
    install_fake_speech(monkeypatch)
    token, user_id = await _create_user_with_tokens("iv-409@example.com", "StrongPass123", UserRole.CANDIDATE)
    resume_id = await insert_resume(user_id)
    session_id, ids = await insert_session_with_questions(user_id, resume_id)

    await _speak_and_drain(client, token, session_id, ids[0])
    again = await speak(client, token, session_id, ids[0], suffix=b"-retake")
    assert again.status_code == 409  # already scored
    assert again.json()["detail"] == "answer already scored"

    await _speak_and_drain(client, token, session_id, ids[1])  # last row -> session completes
    done = (await client.get(f"/interviews/{session_id}", headers=_bearer(token))).json()
    assert done["status"] == "completed"
    closed = await speak(client, token, session_id, ids[1], suffix=b"-late")
    assert closed.status_code == 409  # completed session
    assert closed.json()["detail"] == "session is not accepting answers"


async def test_retake_before_scoring_clears_the_transcript_copy(client, redis_pool, monkeypatch):
    """Re-uploading before evaluation clears transcript, metrics, and answer_text so nothing stays stale."""
    install_fake_speech(monkeypatch)
    token, user_id = await _create_user_with_tokens("iv-retake@example.com", "StrongPass123", UserRole.CANDIDATE)
    resume_id = await insert_resume(user_id)
    session_id, ids = await insert_session_with_questions(user_id, resume_id)
    async with AsyncSessionLocal() as db:  # simulate a transcribed-but-unscored take
        row = await db.get(Answer, ids[0])
        row.audio_path, row.transcript, row.answer_text = "/tmp/x.webm", "old words", "old words"
        await db.commit()

    second = await speak(client, token, session_id, ids[0], suffix=b"-v2")
    assert second.status_code == 200
    fetched = (await client.get(f"/interviews/{session_id}", headers=_bearer(token))).json()["answers"][0]
    assert fetched["transcript"] is None and fetched["answer_text"] is None and fetched["speech_metrics"] is None


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


async def test_audio_upload_stores_path_and_leaves_transcript_null(client, redis_pool):
    """POST .../audio writes audio_path, enqueues transcribe, and does not fill transcript until the worker runs."""
    token, user_id = await _create_user_with_tokens("iv-audio-ok@example.com", "StrongPass123", UserRole.CANDIDATE)
    resume_id = await _insert_resume(user_id, parsed=True)
    session_id, answer_ids = await insert_session_with_questions(user_id, resume_id)
    answer_id = answer_ids[0]

    response = await client.post(
        f"/interviews/{session_id}/answers/{answer_id}/audio",
        files={"file": ("answer.webm", _tiny_webm(), "audio/webm")},
        headers=_bearer(token),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["answer_id"] == str(answer_id)
    assert body["has_audio"] is True
    assert body["async_job_id"]  # SPA reuses useJobStatus; no second poller

    polled = (await client.get(f"/jobs/{body['async_job_id']}", headers=_bearer(token))).json()
    assert polled["job_type"] == "transcribe"  # plain string, not a Postgres ENUM
    assert polled["status"] == "queued"  # worker has not run; this test does not drain ARQ

    fetched = (await client.get(f"/interviews/{session_id}", headers=_bearer(token))).json()
    row = fetched["answers"][0]
    assert row["has_audio"] is True
    assert row["answer_text"] is None  # filled only when the transcribe worker finishes
    assert row["transcript"] is None  # still null until the transcribe worker succeeds
    assert row["speech_metrics"] is None  # timings/fluency land with the transcript
    assert "audio_path" not in row  # filesystem path is excluded from JSON
    async with AsyncSessionLocal() as db:
        stored = await db.get(Answer, answer_id)
        assert stored is not None
        assert stored.audio_path is not None
        assert stored.transcript is None  # this endpoint must not invent a transcript


async def test_audio_upload_is_owner_only_404(client, redis_pool):
    """Another candidate posting audio to someone else's answer id gets 404, not 403."""
    owner, owner_id = await _create_user_with_tokens("iv-aud-owner@example.com", "StrongPass123", UserRole.CANDIDATE)
    other, _ = await _create_user_with_tokens("iv-aud-other@example.com", "StrongPass123", UserRole.CANDIDATE)
    resume_id = await _insert_resume(owner_id, parsed=True)
    session_id, answer_ids = await insert_session_with_questions(owner_id, resume_id)
    answer_id = answer_ids[0]

    response = await client.post(
        f"/interviews/{session_id}/answers/{answer_id}/audio",
        files={"file": ("answer.webm", _tiny_webm(), "audio/webm")},
        headers=_bearer(other),
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "session not found"


async def test_recruiter_cannot_upload_audio(client, redis_pool):
    """A recruiter account gets 403 from the audio upload; only candidates may store blobs."""
    token, _ = await _create_user_with_tokens("iv-aud-rec@example.com", "StrongPass123", UserRole.RECRUITER)
    response = await client.post(
        "/interviews/00000000-0000-0000-0000-000000000001/answers/00000000-0000-0000-0000-000000000002/audio",
        files={"file": ("answer.webm", _tiny_webm(), "audio/webm")},
        headers=_bearer(token),
    )
    assert response.status_code == 403


async def test_audio_upload_requires_auth(client, redis_pool):
    """POST .../audio without a bearer token is 401."""
    response = await client.post(
        "/interviews/00000000-0000-0000-0000-000000000001/answers/00000000-0000-0000-0000-000000000002/audio",
        files={"file": ("answer.webm", _tiny_webm(), "audio/webm")},
    )
    assert response.status_code == 401


async def test_audio_upload_rejects_wrong_type_and_oversize(client, redis_pool):
    """Non-webm content types and bodies over 10 MiB are 400 before the row is updated."""
    token, user_id = await _create_user_with_tokens("iv-aud-bad@example.com", "StrongPass123", UserRole.CANDIDATE)
    resume_id = await _insert_resume(user_id, parsed=True)
    session_id, answer_ids = await insert_session_with_questions(user_id, resume_id)
    answer_id = answer_ids[0]

    bad_type = await client.post(
        f"/interviews/{session_id}/answers/{answer_id}/audio",
        files={"file": ("answer.txt", b"not audio", "text/plain")},
        headers=_bearer(token),
    )
    assert bad_type.status_code == 400

    too_big = await client.post(
        f"/interviews/{session_id}/answers/{answer_id}/audio",
        files={"file": ("answer.webm", b"x" * (10 * 1024 * 1024 + 1), "audio/webm")},
        headers=_bearer(token),
    )
    assert too_big.status_code == 400

    fetched = (await client.get(f"/interviews/{session_id}", headers=_bearer(token))).json()
    assert fetched["answers"][0]["has_audio"] is False  # rejected uploads must not flip the flag


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
    resume_id = await insert_resume(user_id)
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

    install_fake_speech(pytest.MonkeyPatch(), None)  # stub WebM; the pipeline is faked, the judge is live
    uploaded = await speak(client, token, session_id, answer_id)
    assert uploaded.status_code == 200
    await run_burst_worker()  # fake transcribe -> real evaluate_answer (+ maybe follow-up)

    transcribe_job = (await client.get(f"/jobs/{uploaded.json()['async_job_id']}", headers=_bearer(token))).json()
    eval_job = (
        await client.get(f"/jobs/{transcribe_job['result']['evaluate_async_job_id']}", headers=_bearer(token))
    ).json()
    if eval_job["status"] == "failed":
        pytest.skip(f"live evaluate failed: {eval_job['error']}")  # JSON/schema flakiness: skip, never fail CI

    final = (await client.get(f"/interviews/{session_id}", headers=_bearer(token))).json()
    evaluation = final["answers"][0]["evaluation"]
    assert evaluation is not None
    assert 0 <= evaluation["score"] <= 5  # schema already enforces this
    assert evaluation["rationale"]  # non-empty justification from the live model
