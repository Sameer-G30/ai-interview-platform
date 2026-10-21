"""Hardening tests for three flows the endpoint suites only cover in pieces.

Auth tests hit registration edges that `test_auth.py` does not: `is_admin` cannot be self-granted,
the string "admin" is not a role, email is lowercased, and a deactivated account's login looks like
a bad password. Upload-to-parse uses the real PDF pipeline with `embed_text` monkeypatched, so this
file does not load MiniLM. Interview-to-score reuses `interview_fakes` and never calls Ollama or
Whisper. Audio upload is asserted to leave `GET /scores` at 404.
"""

import io  # in-memory PDF and the empty/oversize bodies
import uuid  # resume primary keys come back as UUID strings on the wire

import pymupdf  # builds the one-page PDF the parse worker actually opens
import pytest  # approx() for the renormalized composite
from interview_fakes import (  # same fake judge the scoring tests use; not live Ollama
    FakeInterviewBackend,
    install_fake,
)
from ml.scoring import (  # product weights, so the expected composite tracks Settings
    SIGNAL_BEHAVIORAL,
    SIGNAL_COMMUNICATION,
    SIGNAL_RESUME,
    SIGNAL_TECHNICAL,
    config_from_settings,
    scale_judge_score,
)
from sqlalchemy import func, select  # count rows to prove a rejected upload wrote nothing

from app.auth import service  # register/issue tokens without spending the HTTP rate limit
from app.core.config import get_settings  # the same Settings the worker's scorer reads
from app.core.db import AsyncSessionLocal  # direct reads of embedding / is_active
from app.models.async_job import AsyncJob  # a rejected upload must not enqueue
from app.models.enums import ResumeStatus, UserRole  # parsed vs uploaded; candidate vs recruiter
from app.models.resume import Resume  # embedding is not on the HTTP schema; read the row
from app.models.user import User  # flip is_active for the inactive-login case
from app.workers.settings import run_burst_worker  # in-process ARQ drain, same as the other suites

settings = get_settings()  # cached Settings shared with the app process

# Resume text the ESCO sample matcher already accepts in test_resumes.py. Kept here so this flow
# does not depend on that module's private helper.
_SAMPLE_RESUME_TEXT = """Jane Doe
jane.doe@example.com
+1 555-123-4567

Summary
Experienced software engineer with a passion for building reliable systems.

Experience
Senior Software Engineer at Example Corp (2020-2024)
Built REST APIs using FastAPI and Python. Worked with PostgreSQL, Docker, and Kubernetes.

Education
B.S. Computer Science, State University, 2016-2020

Skills
Python, JavaScript, Docker, Kubernetes, SQL, Machine Learning, Git
"""


def _bearer(access_token: str) -> dict[str, str]:
    """Authorization header the protected routes expect."""
    return {"Authorization": f"Bearer {access_token}"}  # access JWT, never the opaque refresh token


def _fake_embed_text(text: str) -> list[float]:
    """384-d stand-in for MiniLM. The value is constant so this test never loads the real model."""
    del text  # the parse contract only requires a vector, not a meaningful one
    vector = [0.0] * 384  # same width as the pgvector column
    vector[0] = 1.0  # non-zero so a NULL column cannot pass the assertion by accident
    return vector  # resume_parse writes this straight onto resumes.embedding


def _make_pdf_bytes(text: str) -> bytes:
    """One-page PDF in memory. Nothing is written under the repo."""
    document = pymupdf.open()  # empty document
    page = document.new_page()  # a single page the extractor can read
    page.insert_text((50, 50), text, fontsize=11)  # body the section splitter and ESCO matcher see
    pdf_bytes = document.tobytes()  # multipart body
    document.close()  # release the MuPDF handle
    return pdf_bytes  # caller wraps this in BytesIO


async def _create_user(email: str, role: UserRole) -> tuple[str, uuid.UUID]:
    """Insert a user through the service layer and return (access token, user id)."""
    async with AsyncSessionLocal() as session:  # same session factory the app uses
        user = await service.register_user(
            session, email=email, password="StrongPass123", full_name="Flow Tester", role=role
        )
        access_token, _ = await service.issue_token_pair(session, user=user, settings=settings)  # skip HTTP login
        await session.commit()  # the next request must see the row
        return access_token, user.id  # id is assigned at flush inside register_user


async def test_register_cannot_grant_admin_and_rejects_admin_role(client):
    """`is_admin` on the register body is ignored, and role "admin" is 422. There is no third role."""
    created = await client.post(
        "/auth/register",
        json={
            "email": "flow-noadmin@example.com",  # new address
            "password": "StrongPass123",  # meets the 8-character minimum
            "full_name": "No Admin",  # display name
            "role": "recruiter",  # a real role
            "is_admin": True,  # extra field; RegisterRequest does not declare it
        },
    )
    assert created.status_code == 201  # the account is created
    me = await client.get("/auth/me", headers=_bearer(created.json()["access_token"]))  # token from register
    assert me.status_code == 200  # the new access token works
    assert me.json()["role"] == "recruiter"  # JSON value, not the Postgres enum label
    assert me.json()["is_admin"] is False  # registration cannot set the flag

    rejected = await client.post(
        "/auth/register",
        json={"email": "flow-role-admin@example.com", "password": "StrongPass123", "role": "admin"},
    )
    assert rejected.status_code == 422  # UserRole has no ADMIN member


async def test_register_lowercases_email(client):
    """Mixed-case registration stores the lowercase address, and login uses that address."""
    created = await client.post(
        "/auth/register",
        json={"email": "Flow.Case@Example.com", "password": "StrongPass123", "full_name": "Case"},
    )
    assert created.status_code == 201  # created
    me = await client.get("/auth/me", headers=_bearer(created.json()["access_token"]))  # profile
    assert me.json()["email"] == "flow.case@example.com"  # normalized before insert
    logged_in = await client.post(
        "/auth/login",
        json={"email": "flow.case@example.com", "password": "StrongPass123"},
    )
    assert logged_in.status_code == 200  # the normalized address is the login key
    assert logged_in.json()["access_token"]  # a fresh pair, not an error body


async def test_login_inactive_user_matches_bad_password(client):
    """A deactivated account's login is 401 with the same detail as a wrong password."""
    async with AsyncSessionLocal() as session:  # service insert, then flip the flag in this transaction
        user = await service.register_user(
            session,
            email="flow-inactive@example.com",
            password="StrongPass123",
            full_name="Inactive",
            role=UserRole.CANDIDATE,
        )
        user.is_active = False  # soft-disable; login must not explain why
        await session.commit()  # authenticate_user reads the committed flag
    response = await client.post(
        "/auth/login",
        json={"email": "flow-inactive@example.com", "password": "StrongPass123"},
    )
    assert response.status_code == 401  # not 403, and not a token pair
    assert response.json()["detail"] == "incorrect email or password"  # same string as a bad password
    assert "access_token" not in response.json()  # no session was issued


async def test_short_password_and_malformed_bearer_are_rejected(client):
    """Passwords under 8 characters never reach Argon2, and a non-JWT bearer cannot call /auth/me."""
    short = await client.post(
        "/auth/register",
        json={"email": "flow-short@example.com", "password": "short"},
    )
    assert short.status_code == 422  # Field(min_length=8) on RegisterRequest

    me = await client.get("/auth/me", headers={"Authorization": "Bearer not-a-jwt"})  # garbage token
    assert me.status_code == 401  # decode_access_token rejects it
    async with AsyncSessionLocal() as session:  # the 422 must not have inserted a user
        found = await session.scalar(select(User).where(User.email == "flow-short@example.com"))
        assert found is None  # validation failed before register_user


async def test_upload_rejects_empty_and_oversize_before_enqueue(client, redis_pool):
    """An empty PDF and a body over 10 MiB are 400, with no resume row and no async job."""
    del redis_pool  # the fixture attaches the pool; these requests fail before enqueue
    _token, user_id = await _create_user("flow-upload-reject@example.com", UserRole.CANDIDATE)  # candidate
    token = _token  # bearer for both rejects

    empty = await client.post(
        "/resumes",
        files={"file": ("empty.pdf", io.BytesIO(b""), "application/pdf")},  # zero bytes
        headers=_bearer(token),
    )
    assert empty.status_code == 400  # rejected
    assert empty.json()["detail"] == "uploaded file is empty"  # the empty-body message

    oversize = await client.post(
        "/resumes",
        files={"file": ("big.pdf", io.BytesIO(b"x" * (10 * 1024 * 1024 + 1)), "application/pdf")},  # 10 MiB + 1
        headers=_bearer(token),
    )
    assert oversize.status_code == 400  # rejected before PyMuPDF
    assert oversize.json()["detail"] == "file exceeds the 10 MiB upload limit"  # the size message

    async with AsyncSessionLocal() as session:  # neither request may have persisted work
        resumes = await session.scalar(select(func.count()).select_from(Resume).where(Resume.user_id == user_id))
        jobs = await session.scalar(select(func.count()).select_from(AsyncJob).where(AsyncJob.user_id == user_id))
        assert resumes == 0  # no blob row
        assert jobs == 0  # no resume_parse job


async def test_upload_parse_and_text_submit_writes_renormalized_score(client, redis_pool, monkeypatch):
    """Upload → parse (fake embed) → text submit → stored composite. Communication stays null.

    The composite uses the configured weights renormalized over the signals that exist. It is not
    the partial sum that still divides by the full four-signal total ("out of 90").
    """
    del redis_pool  # fixture attaches app.state.redis; the assertions do not touch the pool object
    monkeypatch.setattr("app.workers.tasks.embed_text", _fake_embed_text)  # do not load MiniLM
    install_fake(
        monkeypatch,
        FakeInterviewBackend(
            questions=[{"question_text": "What is a Python list?", "question_kind": "technical"}],  # one question
            evaluation={"score": 4, "rationale": "Clear definition.", "strengths": ["correct"], "improvements": []},
        ),
    )  # score 4 does not spawn a follow-up, so the session completes on this submit
    token, _user_id = await _create_user("flow-score@example.com", UserRole.CANDIDATE)  # owner of the resume

    created = await client.post(
        "/resumes",
        files={"file": ("resume.pdf", io.BytesIO(_make_pdf_bytes(_SAMPLE_RESUME_TEXT)), "application/pdf")},
        headers=_bearer(token),
    )
    assert created.status_code == 201  # stored and queued
    resume_id = created.json()["resume_id"]  # poll target
    job_id = created.json()["async_job_id"]  # resume_parse id
    queued = await client.get(f"/jobs/{job_id}", headers=_bearer(token))  # before the worker
    assert queued.json()["status"] == "queued"  # the API did not parse inline
    assert queued.json()["job_type"] == "resume_parse"  # plain string job type

    await run_burst_worker()  # parse + fake embed, then the queue is empty

    parsed = await client.get(f"/resumes/{resume_id}", headers=_bearer(token))  # results
    assert parsed.status_code == 200  # owner
    parsed_body = parsed.json()  # sections, skills, ATS
    assert parsed_body["status"] == "parsed"  # worker advanced the row
    assert parsed_body["ats_score"] is not None and parsed_body["ats_score"] > 0  # checklist score
    assert "Python" in parsed_body["parsed_data"]["skills"]  # ESCO sample hit
    assert "Docker" in parsed_body["parsed_data"]["skills"]  # second hit, so this is not a stub parse
    done_job = await client.get(f"/jobs/{job_id}", headers=_bearer(token))  # same id the upload returned
    assert done_job.json()["status"] == "succeeded"  # parse finished

    async with AsyncSessionLocal() as session:  # embedding is intentionally absent from ResumeOut
        stored = await session.get(Resume, uuid.UUID(resume_id))  # the row the worker committed
        assert stored is not None  # upload inserted it
        assert stored.status == ResumeStatus.PARSED  # same fact as the HTTP body
        assert stored.embedding is not None  # parsed implies embedded, in this same worker pass
        assert len(list(stored.embedding)) == 384  # pgvector width; the fake vector, not MiniLM weights

    started = await client.post("/interviews", json={"resume_id": resume_id}, headers=_bearer(token))  # practice
    assert started.status_code == 201, started.text  # generate enqueued
    session_id = started.json()["session_id"]  # score id equals the session id
    await run_burst_worker()  # fake generate writes the question; no Ollama

    session_body = (await client.get(f"/interviews/{session_id}", headers=_bearer(token))).json()  # questions
    assert session_body["answers"][0]["answer_text"] is None  # generate does not invent an answer
    answer_id = session_body["answers"][0]["id"]  # the only question
    answer_text = "A mutable ordered sequence of objects."  # the only scoring path is this text
    submitted = await client.post(
        f"/interviews/{session_id}/answers/{answer_id}",
        json={"answer_text": answer_text},  # text submit enqueues interview_evaluate, not transcribe
        headers=_bearer(token),
    )
    assert submitted.status_code == 200, submitted.text  # queued
    await run_burst_worker()  # fake evaluate + aggregate_session; no second model

    final_session = (await client.get(f"/interviews/{session_id}", headers=_bearer(token))).json()  # after evaluate
    assert final_session["status"] == "completed"  # one passing answer, no follow-up
    assert final_session["answers"][0]["answer_text"] == answer_text  # stored text, not a transcript copy
    assert final_session["answers"][0]["transcript"] is None  # text submit does not invent speech

    scored = await client.get(f"/scores/{session_id}", headers=_bearer(token))  # stored row, not a recompute
    assert scored.status_code == 200, scored.text  # owner
    body = scored.json()  # ScoreOut
    ats = float(parsed_body["ats_score"])  # resume signal is the parsed ATS
    technical = scale_judge_score(4)  # judge 0–5 times 20 → 0–100
    assert body["resume_score"] == pytest.approx(ats)  # the upload's ATS, not a hardcoded fixture
    assert body["technical_score"] == pytest.approx(technical)  # 4 * 20
    assert body["communication_score"] is None  # text-only; not stored as 0
    assert body["behavioral_score"] is None  # no behavioral question
    assert SIGNAL_COMMUNICATION in body["attribution"]["omitted"]  # reconstructable omission
    assert SIGNAL_BEHAVIORAL in body["attribution"]["omitted"]  # same
    weights = config_from_settings(settings)  # SCORE_WEIGHT_* from Settings, same as the worker
    applied = weights.applied({SIGNAL_RESUME, SIGNAL_TECHNICAL})  # renormalize over the two present signals
    assert sum(applied.values()) == pytest.approx(1.0)  # the applied weights are a full share, not 50/90
    expected = applied[SIGNAL_RESUME] * ats + applied[SIGNAL_TECHNICAL] * technical  # 0–100 composite
    assert body["composite_score"] == pytest.approx(expected)  # stored value matches that formula
    assert 0.0 <= body["composite_score"] <= 100.0  # not an unscaled sum of the raw weights
    raw = weights.as_dict()  # configured weights before omission
    full_mass = sum(raw.values())  # 90 with the default 20/30/25/15
    if raw[SIGNAL_COMMUNICATION] > 0 or raw[SIGNAL_BEHAVIORAL] > 0:  # otherwise the two formulas coincide
        divided_by_full = (raw[SIGNAL_RESUME] / full_mass) * ats + (raw[SIGNAL_TECHNICAL] / full_mass) * technical
        assert body["composite_score"] != pytest.approx(divided_by_full)  # omitted weights left the denominator
    again = (await client.get(f"/scores/{session_id}", headers=_bearer(token))).json()  # second read
    assert again == body  # GET did not recompute or rewrite the stored row


async def test_audio_upload_does_not_write_a_score(client, redis_pool, monkeypatch):
    """Audio enqueue is transcribe only. With no text submit, GET /scores stays 404 and answer_text stays null."""
    del redis_pool  # pool is attached for the enqueue; this test does not drain it after the audio post
    install_fake(monkeypatch, FakeInterviewBackend())  # generate one question; do not call Ollama
    token, user_id = await _create_user("flow-audio-noscore@example.com", UserRole.CANDIDATE)  # candidate
    async with AsyncSessionLocal() as session:  # a parsed resume without going through MiniLM or a second upload
        resume = Resume(
            user_id=user_id,  # owner
            file_path="/tmp/flow-audio-noscore.pdf",  # never opened; generate only reads parsed_data
            original_filename="resume.pdf",  # display name
            status=ResumeStatus.PARSED,  # POST /interviews requires parsed
            parsed_data={"sections": {}, "skills": ["Python"], "email": None, "phone": None},  # prompt skills
            ats_score=70.0,  # unused until a text submit completes the session
        )
        session.add(resume)  # insert
        await session.commit()  # start must see it
        resume_id = str(resume.id)  # JSON resume_id is a string

    started = await client.post("/interviews", json={"resume_id": resume_id}, headers=_bearer(token))  # practice
    assert started.status_code == 201, started.text  # generate queued
    session_id = started.json()["session_id"]  # later score lookup
    await run_burst_worker()  # generate only; the queue is empty afterward
    answer_id = (await client.get(f"/interviews/{session_id}", headers=_bearer(token))).json()["answers"][0]["id"]

    uploaded = await client.post(
        f"/interviews/{session_id}/answers/{answer_id}/audio",
        files={"file": ("answer.webm", b"webm-test-bytes", "audio/webm")},  # upload does not decode this
        headers=_bearer(token),
    )
    assert uploaded.status_code == 200, uploaded.text  # blob stored, transcribe queued
    assert uploaded.json()["async_job_id"]  # a job exists
    # Do not burst: the queued job is transcribe, and this test must not load Whisper.

    polled = await client.get(f"/jobs/{uploaded.json()['async_job_id']}", headers=_bearer(token))  # still queued
    assert polled.json()["job_type"] == "transcribe"  # not interview_evaluate
    assert polled.json()["status"] == "queued"  # worker has not run
    fetched = (await client.get(f"/interviews/{session_id}", headers=_bearer(token))).json()  # session read
    assert fetched["answers"][0]["answer_text"] is None  # audio did not copy itself into the scoring text
    assert fetched["answers"][0]["transcript"] is None  # no transcript until a worker runs
    missing = await client.get(f"/scores/{session_id}", headers=_bearer(token))  # no composite yet
    assert missing.status_code == 404  # audio is not a scoring path
