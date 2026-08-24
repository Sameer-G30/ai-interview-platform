"""Integration tests for `/postings/*`, against live Docker Postgres and Redis.

`app.workers.tasks.embed_text` is monkeypatched to a deterministic hashing-trick embedder so these
tests never need real SBERT model weights (no network dependency, and instant instead of a
multi-second model load) - see `_fake_embed_text` below and `test_ml_matching.py`'s docstring for
the one real-MiniLM smoke test that exercises the actual model.
"""

from app.auth import service  # register_user/issue_token_pair, used to mint tokens without hitting rate limits
from app.core.config import get_settings  # same Settings the app uses, for token expiry
from app.core.db import AsyncSessionLocal  # session factory identical to the app's DI
from app.models.enums import UserRole  # role passed to register_user
from app.workers.settings import run_burst_worker  # in-process ARQ drain used after enqueue

settings = get_settings()  # cached; tests share the process Settings with the app


def _fake_embed_text(text: str) -> list[float]:
    """Deterministic 384-d hashing-trick embedding: word overlap between two texts increases cosine
    similarity, which is all these tests need (real semantic quality is exercised in test_ml_matching.py)."""
    vector = [0.0] * 384
    for word in text.lower().split():
        vector[hash(word) % 384] += 1.0
    return vector


async def _create_user_with_tokens(email: str, password: str, role: UserRole) -> str:
    """Register a user via the service layer and return an access token (Bearer, not the refresh token)."""
    async with AsyncSessionLocal() as session:
        user = await service.register_user(
            session, email=email, password=password, full_name="Posting Tester", role=role
        )
        access_token, _ = await service.issue_token_pair(session, user=user, settings=settings)
        await session.commit()
    return access_token


def _bearer(access_token: str) -> dict[str, str]:
    """Build the Authorization header the postings routes expect."""
    return {"Authorization": f"Bearer {access_token}"}


_POSTING_BODY = {
    "title": "Backend Engineer",
    "description": "Build APIs with FastAPI and Postgres.",
    "required_skills": "Python, FastAPI, PostgreSQL",
}


async def test_recruiter_can_create_and_get_posting(client, redis_pool, monkeypatch):
    """POST /postings creates an owned posting and enqueues embedding; GET reads it back."""
    monkeypatch.setattr("app.workers.tasks.embed_text", _fake_embed_text)
    access_token = await _create_user_with_tokens("posting-create@example.com", "StrongPass123", UserRole.RECRUITER)

    created = await client.post("/postings", json=_POSTING_BODY, headers=_bearer(access_token))
    assert created.status_code == 201
    body = created.json()
    assert body["posting"]["title"] == "Backend Engineer"
    assert body["posting"]["is_active"] is True
    assert body["posting"]["has_embedding"] is False  # worker has not run yet
    assert body["async_job_id"]

    posting_id = body["posting"]["id"]
    fetched = await client.get(f"/postings/{posting_id}", headers=_bearer(access_token))
    assert fetched.status_code == 200
    assert fetched.json()["id"] == posting_id

    await run_burst_worker()  # drains posting_embed

    reread = await client.get(f"/postings/{posting_id}", headers=_bearer(access_token))
    assert reread.status_code == 200
    assert reread.json()["has_embedding"] is True  # embedding worker succeeded

    polled_job = await client.get(f"/jobs/{body['async_job_id']}", headers=_bearer(access_token))
    assert polled_job.status_code == 200
    assert polled_job.json()["status"] == "succeeded"


async def test_recruiter_can_list_only_own_postings(client, redis_pool, monkeypatch):
    """GET /postings returns only the caller's own postings, newest first."""
    monkeypatch.setattr("app.workers.tasks.embed_text", _fake_embed_text)
    owner_token = await _create_user_with_tokens("posting-list-owner@example.com", "StrongPass123", UserRole.RECRUITER)
    other_token = await _create_user_with_tokens("posting-list-other@example.com", "StrongPass123", UserRole.RECRUITER)

    await client.post("/postings", json={**_POSTING_BODY, "title": "First"}, headers=_bearer(owner_token))
    await client.post("/postings", json={**_POSTING_BODY, "title": "Second"}, headers=_bearer(owner_token))
    await client.post("/postings", json={**_POSTING_BODY, "title": "Someone else's"}, headers=_bearer(other_token))

    listed = await client.get("/postings", headers=_bearer(owner_token))
    assert listed.status_code == 200
    titles = [posting["title"] for posting in listed.json()]
    assert titles == ["Second", "First"]  # newest first; "Someone else's" is not visible


async def test_recruiter_can_deactivate_own_posting(client, redis_pool, monkeypatch):
    """PATCH /postings/{id} flips is_active without a hard delete."""
    monkeypatch.setattr("app.workers.tasks.embed_text", _fake_embed_text)
    access_token = await _create_user_with_tokens("posting-deactivate@example.com", "StrongPass123", UserRole.RECRUITER)

    created = await client.post("/postings", json=_POSTING_BODY, headers=_bearer(access_token))
    posting_id = created.json()["posting"]["id"]

    patched = await client.patch(f"/postings/{posting_id}", json={"is_active": False}, headers=_bearer(access_token))
    assert patched.status_code == 200
    assert patched.json()["is_active"] is False

    reread = await client.get(f"/postings/{posting_id}", headers=_bearer(access_token))
    assert reread.json()["is_active"] is False


async def test_posting_owner_only_404_for_another_recruiter(client, redis_pool, monkeypatch):
    """A second recruiter reading/patching someone else's posting id gets 404, not 403."""
    monkeypatch.setattr("app.workers.tasks.embed_text", _fake_embed_text)
    owner_token = await _create_user_with_tokens("posting-owner@example.com", "StrongPass123", UserRole.RECRUITER)
    other_token = await _create_user_with_tokens("posting-other@example.com", "StrongPass123", UserRole.RECRUITER)

    created = await client.post("/postings", json=_POSTING_BODY, headers=_bearer(owner_token))
    posting_id = created.json()["posting"]["id"]

    get_response = await client.get(f"/postings/{posting_id}", headers=_bearer(other_token))
    assert get_response.status_code == 404
    assert get_response.json()["detail"] == "posting not found"

    patch_response = await client.patch(
        f"/postings/{posting_id}", json={"is_active": False}, headers=_bearer(other_token)
    )
    assert patch_response.status_code == 404


async def test_posting_unknown_id_is_404(client, redis_pool):
    """GET /postings/{id} for a UUID that was never inserted is 404."""
    access_token = await _create_user_with_tokens("posting-missing@example.com", "StrongPass123", UserRole.RECRUITER)
    response = await client.get(
        "/postings/00000000-0000-0000-0000-000000000001",
        headers=_bearer(access_token),
    )
    assert response.status_code == 404


async def test_candidate_cannot_write_postings(client, redis_pool):
    """A candidate account gets 403 from POST/PATCH /postings; only recruiters may manage postings."""
    access_token = await _create_user_with_tokens("posting-candidate@example.com", "StrongPass123", UserRole.CANDIDATE)

    created = await client.post("/postings", json=_POSTING_BODY, headers=_bearer(access_token))
    assert created.status_code == 403

    listed = await client.get("/postings", headers=_bearer(access_token))
    assert listed.status_code == 403


async def test_postings_require_auth(client, redis_pool):
    """POST /postings without a bearer token is 401, matching other protected routes."""
    response = await client.post("/postings", json=_POSTING_BODY)
    assert response.status_code == 401
