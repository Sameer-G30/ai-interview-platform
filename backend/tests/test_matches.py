"""Integration tests for `GET /matches`, against live Docker Postgres and Redis.

Both `resume_parse` and `posting_embed` go through the real burst worker so `parsed_data`/`skills`
and `embedding` are populated exactly the way production does; only the SBERT model call itself is
monkeypatched to the same deterministic hashing-trick embedder `test_postings.py` uses, so ranking
by word overlap is fast and offline-safe. `test_ml_matching.py` covers `SbertBackend`/`TfidfBackend`
/`skill_gap` directly and includes the one real-MiniLM smoke test.
"""

import io  # in-memory PDF bytes for multipart upload

import pymupdf  # builds tiny synthetic PDFs for the resume side of these tests

from app.auth import service  # register_user/issue_token_pair, used to mint tokens without hitting rate limits
from app.core.config import get_settings  # same Settings the app uses, for token expiry
from app.core.db import AsyncSessionLocal  # session factory identical to the app's DI
from app.models.enums import UserRole  # role passed to register_user
from app.workers.settings import run_burst_worker  # in-process ARQ drain used after enqueue

settings = get_settings()  # cached; tests share the process Settings with the app


def _fake_embed_text(text: str) -> list[float]:
    """Same deterministic hashing-trick embedder as test_postings.py: word overlap -> higher cosine similarity."""
    vector = [0.0] * 384
    for word in text.lower().split():
        vector[hash(word) % 384] += 1.0
    return vector


async def _create_user_with_tokens(email: str, password: str, role: UserRole) -> str:
    """Register a user via the service layer and return an access token (Bearer, not the refresh token)."""
    async with AsyncSessionLocal() as session:
        user = await service.register_user(session, email=email, password=password, full_name="Match Tester", role=role)
        access_token, _ = await service.issue_token_pair(session, user=user, settings=settings)
        await session.commit()
    return access_token


def _bearer(access_token: str) -> dict[str, str]:
    """Build the Authorization header the matches/resumes/postings routes expect."""
    return {"Authorization": f"Bearer {access_token}"}


def _make_pdf_bytes(text: str) -> bytes:
    """Build a one-page PDF in memory with the given text (never written to disk)."""
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((50, 50), text, fontsize=11)
    pdf_bytes = document.tobytes()
    document.close()
    return pdf_bytes


_RESUME_TEXT = """Jane Doe
jane.doe@example.com
+1 555-123-4567

Summary
Experienced backend engineer focused on distributed systems and cloud infrastructure.

Experience
Senior Software Engineer at Example Corp (2020-2024)
Built REST APIs using FastAPI and Python. Worked with PostgreSQL, Docker, and Kubernetes.

Education
B.S. Computer Science, State University, 2016-2020

Skills
Python, Docker, Kubernetes, SQL, Git
"""


async def _upload_and_parse_resume(client, access_token: str) -> str:
    """Upload the shared sample resume, drain the worker, and return the resume id (status=parsed)."""
    created = await client.post(
        "/resumes",
        files={"file": ("resume.pdf", io.BytesIO(_make_pdf_bytes(_RESUME_TEXT)), "application/pdf")},
        headers=_bearer(access_token),
    )
    assert created.status_code == 201
    resume_id = created.json()["resume_id"]
    await run_burst_worker()
    return resume_id


async def _create_and_embed_posting(
    client, access_token: str, *, title: str, description: str, required_skills: str
) -> str:
    """Create one posting and drain the worker so it has an embedding by the time the test reads /matches."""
    created = await client.post(
        "/postings",
        json={"title": title, "description": description, "required_skills": required_skills},
        headers=_bearer(access_token),
    )
    assert created.status_code == 201
    posting_id = created.json()["posting"]["id"]
    await run_burst_worker()
    return posting_id


async def test_matches_ranks_similar_posting_above_dissimilar_one(client, redis_pool, monkeypatch):
    """A posting whose text overlaps heavily with the resume ranks above one that shares no words."""
    monkeypatch.setattr("app.workers.tasks.embed_text", _fake_embed_text)
    candidate_token = await _create_user_with_tokens("match-candidate@example.com", "StrongPass123", UserRole.CANDIDATE)
    recruiter_token = await _create_user_with_tokens("match-recruiter@example.com", "StrongPass123", UserRole.RECRUITER)

    resume_id = await _upload_and_parse_resume(client, candidate_token)

    similar_id = await _create_and_embed_posting(
        client,
        recruiter_token,
        title="Backend Engineer",
        description="Build REST APIs using FastAPI and Python. Work with PostgreSQL, Docker, and Kubernetes.",
        required_skills="Python, Docker, Kubernetes",
    )
    dissimilar_id = await _create_and_embed_posting(
        client,
        recruiter_token,
        title="Marine biologist",
        description="Study coral reef ecosystems and ocean wildlife conservation programs.",
        required_skills="",
    )

    response = await client.get(f"/matches?resume_id={resume_id}", headers=_bearer(candidate_token))
    assert response.status_code == 200
    body = response.json()
    assert body["resume_id"] == resume_id
    matches_by_id = {match["posting_id"]: match for match in body["matches"]}
    assert matches_by_id[similar_id]["score"] > matches_by_id[dissimilar_id]["score"]
    # Ranked list is sorted best-first.
    assert body["matches"][0]["posting_id"] == similar_id


async def test_matches_reports_skill_gap(client, redis_pool, monkeypatch):
    """A posting requiring a skill the resume lacks shows up in missing_skills, not matched_skills."""
    monkeypatch.setattr("app.workers.tasks.embed_text", _fake_embed_text)
    candidate_token = await _create_user_with_tokens(
        "match-gap-candidate@example.com", "StrongPass123", UserRole.CANDIDATE
    )
    recruiter_token = await _create_user_with_tokens(
        "match-gap-recruiter@example.com", "StrongPass123", UserRole.RECRUITER
    )

    resume_id = await _upload_and_parse_resume(client, candidate_token)
    posting_id = await _create_and_embed_posting(
        client,
        recruiter_token,
        title="Full-stack role",
        description="Python backend plus a React frontend.",
        required_skills="Python, React, MongoDB",
    )

    response = await client.get(f"/matches?resume_id={resume_id}", headers=_bearer(candidate_token))
    assert response.status_code == 200
    match = next(match for match in response.json()["matches"] if match["posting_id"] == posting_id)
    assert "Python" in match["matched_skills"]
    assert "React" in match["missing_skills"]
    assert "MongoDB" in match["missing_skills"]


async def test_matches_defaults_to_latest_parsed_resume(client, redis_pool, monkeypatch):
    """Omitting ?resume_id= uses the caller's own most recently parsed resume."""
    monkeypatch.setattr("app.workers.tasks.embed_text", _fake_embed_text)
    candidate_token = await _create_user_with_tokens(
        "match-implicit@example.com", "StrongPass123", UserRole.CANDIDATE
    )
    recruiter_token = await _create_user_with_tokens(
        "match-implicit-recruiter@example.com", "StrongPass123", UserRole.RECRUITER
    )

    resume_id = await _upload_and_parse_resume(client, candidate_token)
    await _create_and_embed_posting(
        client,
        recruiter_token,
        title="Backend Engineer",
        description="Python and PostgreSQL work.",
        required_skills="Python",
    )

    response = await client.get("/matches", headers=_bearer(candidate_token))
    assert response.status_code == 200
    assert response.json()["resume_id"] == resume_id


async def test_matches_404_when_no_parsed_resume_exists(client, redis_pool):
    """A candidate with no parsed resume at all gets 404 from GET /matches with no resume_id."""
    candidate_token = await _create_user_with_tokens("match-none@example.com", "StrongPass123", UserRole.CANDIDATE)
    response = await client.get("/matches", headers=_bearer(candidate_token))
    assert response.status_code == 404


async def test_matches_resume_id_owner_only_404(client, redis_pool, monkeypatch):
    """?resume_id= belonging to another candidate is 404, not 403 (ids not enumerable)."""
    monkeypatch.setattr("app.workers.tasks.embed_text", _fake_embed_text)
    owner_token = await _create_user_with_tokens("match-owner@example.com", "StrongPass123", UserRole.CANDIDATE)
    other_token = await _create_user_with_tokens("match-other@example.com", "StrongPass123", UserRole.CANDIDATE)

    resume_id = await _upload_and_parse_resume(client, owner_token)

    response = await client.get(f"/matches?resume_id={resume_id}", headers=_bearer(other_token))
    assert response.status_code == 404


async def test_matches_resume_id_not_yet_parsed_is_409(client, redis_pool):
    """?resume_id= for a resume that exists but hasn't finished parsing yet is 409, not 404."""
    candidate_token = await _create_user_with_tokens("match-pending@example.com", "StrongPass123", UserRole.CANDIDATE)
    created = await client.post(
        "/resumes",
        files={"file": ("resume.pdf", io.BytesIO(_make_pdf_bytes(_RESUME_TEXT)), "application/pdf")},
        headers=_bearer(candidate_token),
    )
    resume_id = created.json()["resume_id"]  # worker not drained; still status=uploaded

    response = await client.get(f"/matches?resume_id={resume_id}", headers=_bearer(candidate_token))
    assert response.status_code == 409


async def test_matches_requires_candidate_role(client, redis_pool):
    """A recruiter calling GET /matches gets 403; matching is candidate-only."""
    recruiter_token = await _create_user_with_tokens(
        "match-recruiter-role@example.com", "StrongPass123", UserRole.RECRUITER
    )
    response = await client.get("/matches", headers=_bearer(recruiter_token))
    assert response.status_code == 403
