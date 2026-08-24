"""Integration tests for resume upload -> enqueue -> worker parse, against live Docker Postgres and Redis.

A burst ARQ worker runs in-process (same pattern as `test_jobs.py`) so success/failure can be
asserted without racing a background worker process. PDFs are generated on the fly with PyMuPDF
(never written to the repo) so no real resume content ever touches git history.
"""

import io  # in-memory PDF bytes for multipart upload, never written to disk by the test itself

import pymupdf  # builds tiny synthetic PDFs for the tests below

from app.auth import service  # register_user/issue_token_pair, used to mint tokens without hitting rate limits
from app.core.config import get_settings  # same Settings the app uses, for token expiry
from app.core.db import AsyncSessionLocal  # session factory identical to the app's DI
from app.models.enums import UserRole  # role passed to register_user
from app.workers.settings import run_burst_worker  # in-process ARQ drain used after enqueue

settings = get_settings()  # cached; tests share the process Settings with the app


async def _create_user_with_tokens(email: str, password: str, role: UserRole) -> str:
    """Register a user via the service layer and return an access token (Bearer, not the refresh token)."""
    async with AsyncSessionLocal() as session:
        user = await service.register_user(
            session, email=email, password=password, full_name="Resume Tester", role=role
        )
        access_token, _ = await service.issue_token_pair(session, user=user, settings=settings)
        await session.commit()
    return access_token


def _bearer(access_token: str) -> dict[str, str]:
    """Build the Authorization header the resumes routes expect."""
    return {"Authorization": f"Bearer {access_token}"}


def _make_pdf_bytes(text: str | None) -> bytes:
    """Build a one-page PDF in memory. `text=None` produces a page with no extractable text at all,
    which is how the "parse failure" test below deterministically triggers `ResumeParseError`
    without needing a genuinely corrupt file."""
    document = pymupdf.open()
    page = document.new_page()
    if text:
        page.insert_text((50, 50), text, fontsize=11)
    pdf_bytes = document.tobytes()
    document.close()
    return pdf_bytes


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


async def test_upload_enqueues_and_returns_queued_resume(client, redis_pool):
    """POST /resumes stores the file, inserts a queued/uploaded resume, and returns both ids."""
    access_token = await _create_user_with_tokens("resume-upload@example.com", "StrongPass123", UserRole.CANDIDATE)

    response = await client.post(
        "/resumes",
        files={"file": ("resume.pdf", io.BytesIO(_make_pdf_bytes(_SAMPLE_RESUME_TEXT)), "application/pdf")},
        headers=_bearer(access_token),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "uploaded"
    assert body["resume_id"]
    assert body["async_job_id"]

    polled_resume = await client.get(f"/resumes/{body['resume_id']}", headers=_bearer(access_token))
    assert polled_resume.status_code == 200
    assert polled_resume.json()["status"] == "uploaded"  # worker has not run yet

    polled_job = await client.get(f"/jobs/{body['async_job_id']}", headers=_bearer(access_token))
    assert polled_job.status_code == 200
    assert polled_job.json()["job_type"] == "resume_parse"
    assert polled_job.json()["status"] == "queued"


async def test_worker_parses_resume_and_sets_ats_score(client, redis_pool):
    """After a burst worker drains the queue, the resume is parsed with matched skills and a score."""
    access_token = await _create_user_with_tokens("resume-parse-ok@example.com", "StrongPass123", UserRole.CANDIDATE)

    created = await client.post(
        "/resumes",
        files={"file": ("resume.pdf", io.BytesIO(_make_pdf_bytes(_SAMPLE_RESUME_TEXT)), "application/pdf")},
        headers=_bearer(access_token),
    )
    assert created.status_code == 201
    resume_id = created.json()["resume_id"]
    job_id = created.json()["async_job_id"]

    await run_burst_worker()  # in-process ARQ worker; runs resume_parse then exits

    polled_resume = await client.get(f"/resumes/{resume_id}", headers=_bearer(access_token))
    assert polled_resume.status_code == 200
    body = polled_resume.json()
    assert body["status"] == "parsed"
    assert body["ats_score"] is not None
    assert body["ats_score"] > 0
    assert "Python" in body["parsed_data"]["skills"]
    assert "Docker" in body["parsed_data"]["skills"]
    assert body["parsed_data"]["email"] == "jane.doe@example.com"

    polled_job = await client.get(f"/jobs/{job_id}", headers=_bearer(access_token))
    assert polled_job.status_code == 200
    job_body = polled_job.json()
    assert job_body["status"] == "succeeded"
    assert job_body["result"]["resume_id"] == resume_id
    assert job_body["result"]["ats_score"] == body["ats_score"]


async def test_worker_marks_resume_failed_when_no_text_is_extractable(client, redis_pool):
    """A PDF with no extractable text ends as a failed resume and a failed async job, not a crash."""
    access_token = await _create_user_with_tokens("resume-parse-fail@example.com", "StrongPass123", UserRole.CANDIDATE)

    created = await client.post(
        "/resumes",
        files={"file": ("blank.pdf", io.BytesIO(_make_pdf_bytes(None)), "application/pdf")},
        headers=_bearer(access_token),
    )
    assert created.status_code == 201
    resume_id = created.json()["resume_id"]
    job_id = created.json()["async_job_id"]

    await run_burst_worker()

    polled_resume = await client.get(f"/resumes/{resume_id}", headers=_bearer(access_token))
    assert polled_resume.status_code == 200
    body = polled_resume.json()
    assert body["status"] == "failed"
    assert body["ats_score"] is None
    assert body["parsed_data"] is None

    polled_job = await client.get(f"/jobs/{job_id}", headers=_bearer(access_token))
    assert polled_job.status_code == 200
    job_body = polled_job.json()
    assert job_body["status"] == "failed"
    assert job_body["error"] is not None


async def test_resume_get_is_owner_only(client, redis_pool):
    """A second candidate polling someone else's resume id gets 404, not 403 (ids not enumerable)."""
    owner_token = await _create_user_with_tokens("resume-owner@example.com", "StrongPass123", UserRole.CANDIDATE)
    other_token = await _create_user_with_tokens("resume-other@example.com", "StrongPass123", UserRole.CANDIDATE)

    created = await client.post(
        "/resumes",
        files={"file": ("resume.pdf", io.BytesIO(_make_pdf_bytes(_SAMPLE_RESUME_TEXT)), "application/pdf")},
        headers=_bearer(owner_token),
    )
    resume_id = created.json()["resume_id"]

    response = await client.get(f"/resumes/{resume_id}", headers=_bearer(other_token))
    assert response.status_code == 404
    assert response.json()["detail"] == "resume not found"


async def test_resume_get_unknown_id_is_404(client, redis_pool):
    """GET /resumes/{id} for a UUID that was never inserted is 404."""
    access_token = await _create_user_with_tokens("resume-missing@example.com", "StrongPass123", UserRole.CANDIDATE)
    response = await client.get(
        "/resumes/00000000-0000-0000-0000-000000000001",
        headers=_bearer(access_token),
    )
    assert response.status_code == 404


async def test_recruiter_cannot_upload_resume(client, redis_pool):
    """A recruiter account gets 403 from POST /resumes; only candidates may upload."""
    access_token = await _create_user_with_tokens("resume-recruiter@example.com", "StrongPass123", UserRole.RECRUITER)

    response = await client.post(
        "/resumes",
        files={"file": ("resume.pdf", io.BytesIO(_make_pdf_bytes(_SAMPLE_RESUME_TEXT)), "application/pdf")},
        headers=_bearer(access_token),
    )
    assert response.status_code == 403


async def test_upload_rejects_non_pdf_content_type(client, redis_pool):
    """A non-PDF content type is rejected with 400 before anything is written to disk or Postgres."""
    access_token = await _create_user_with_tokens("resume-badtype@example.com", "StrongPass123", UserRole.CANDIDATE)

    response = await client.post(
        "/resumes",
        files={"file": ("resume.txt", io.BytesIO(b"not a pdf"), "text/plain")},
        headers=_bearer(access_token),
    )
    assert response.status_code == 400


async def test_upload_requires_auth(client, redis_pool):
    """POST /resumes without a bearer token is 401, matching other protected routes."""
    response = await client.post(
        "/resumes",
        files={"file": ("resume.pdf", io.BytesIO(_make_pdf_bytes(_SAMPLE_RESUME_TEXT)), "application/pdf")},
    )
    assert response.status_code == 401
