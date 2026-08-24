"""Integration tests for enqueue + poll against live Docker Postgres and Redis.

A burst ARQ worker is run in-process (not a separate OS process) so the suite can assert
succeeded/failed without racing a background worker. POST /jobs/demo and GET /jobs/{id} still
go through HTTP so ownership and auth are exercised end to end.
"""

from app.auth import service  # register_user/issue_token_pair, used to mint tokens without hitting rate limits
from app.core.config import get_settings  # same Settings the app uses, for token expiry
from app.core.db import AsyncSessionLocal  # session factory identical to the app's DI
from app.models.enums import UserRole  # role passed to register_user
from app.workers.settings import run_burst_worker  # in-process ARQ drain used after enqueue

settings = get_settings()  # cached; tests share the process Settings with the app


async def _create_user_with_tokens(email: str, password: str) -> tuple[str, str]:
    """Register a user via the service layer and return (access_token, refresh_token)."""
    async with AsyncSessionLocal() as session:  # one transaction for user + refresh row
        user = await service.register_user(
            session, email=email, password=password, full_name="Queue Tester", role=UserRole.CANDIDATE
        )
        access_token, refresh_token = await service.issue_token_pair(session, user=user, settings=settings)
        await session.commit()  # persist before the HTTP calls in the test body
    return access_token, refresh_token  # Bearer access token is what GET/POST /jobs need


def _bearer(access_token: str) -> dict[str, str]:
    """Build the Authorization header the jobs routes expect."""
    return {"Authorization": f"Bearer {access_token}"}  # access JWT, not the opaque refresh token


async def test_demo_enqueue_returns_queued_without_a_worker(client, redis_pool):
    """POST /jobs/demo writes a queued row and returns immediately; GET still shows queued until a worker runs."""
    access_token, _ = await _create_user_with_tokens("queue-queued@example.com", "StrongPass123")

    created = await client.post(
        "/jobs/demo",
        json={"message": "hello queued", "sleep_ms": 0},
        headers=_bearer(access_token),
    )
    assert created.status_code == 201
    body = created.json()
    assert body["status"] == "queued"  # worker has not run yet
    assert body["job_type"] == "demo_echo"
    assert body["result"] is None

    polled = await client.get(f"/jobs/{body['id']}", headers=_bearer(access_token))
    assert polled.status_code == 200
    assert polled.json()["status"] == "queued"  # still queued because we did not drain the worker


async def test_demo_job_succeeds_after_worker_runs(client, redis_pool):
    """After a burst worker drains the queue, GET /jobs/{id} is succeeded and result.echo matches the message."""
    access_token, _ = await _create_user_with_tokens("queue-ok@example.com", "StrongPass123")

    created = await client.post(
        "/jobs/demo",
        json={"message": "hello worker", "sleep_ms": 0},
        headers=_bearer(access_token),
    )
    assert created.status_code == 201
    job_id = created.json()["id"]

    await run_burst_worker()  # in-process ARQ worker; processes the Redis job then exits

    polled = await client.get(f"/jobs/{job_id}", headers=_bearer(access_token))
    assert polled.status_code == 200
    body = polled.json()
    assert body["status"] == "succeeded"
    assert body["result"] == {"echo": "hello worker"}
    assert body["error"] is None


async def test_demo_job_fails_after_worker_runs(client, redis_pool):
    """POST /jobs/demo with fail=true ends as failed with a short error once the worker runs."""
    access_token, _ = await _create_user_with_tokens("queue-fail@example.com", "StrongPass123")

    created = await client.post(
        "/jobs/demo",
        json={"message": "boom from test", "sleep_ms": 0, "fail": True},
        headers=_bearer(access_token),
    )
    assert created.status_code == 201
    job_id = created.json()["id"]

    await run_burst_worker()  # demo_fail raises; tracked wrapper writes FAILED then re-raises

    polled = await client.get(f"/jobs/{job_id}", headers=_bearer(access_token))
    assert polled.status_code == 200
    body = polled.json()
    assert body["status"] == "failed"
    assert body["result"] is None
    assert body["error"] is not None
    assert "boom from test" in body["error"]  # handler reason is preserved in the short summary


async def test_job_get_requires_auth(client, redis_pool):
    """GET /jobs/{id} without a bearer token is 401, matching other protected routes."""
    access_token, _ = await _create_user_with_tokens("queue-unauth@example.com", "StrongPass123")
    created = await client.post("/jobs/demo", json={"message": "x"}, headers=_bearer(access_token))
    job_id = created.json()["id"]

    response = await client.get(f"/jobs/{job_id}")  # no Authorization header
    assert response.status_code == 401


async def test_job_get_is_owner_only(client, redis_pool):
    """A second user polling someone else's job id gets 404, not 403, so ids are not enumerable."""
    owner_access, _ = await _create_user_with_tokens("queue-owner@example.com", "StrongPass123")
    other_access, _ = await _create_user_with_tokens("queue-other@example.com", "StrongPass123")

    created = await client.post(
        "/jobs/demo",
        json={"message": "secret"},
        headers=_bearer(owner_access),
    )
    job_id = created.json()["id"]

    response = await client.get(f"/jobs/{job_id}", headers=_bearer(other_access))
    assert response.status_code == 404
    assert response.json()["detail"] == "job not found"


async def test_job_get_unknown_id_is_404(client, redis_pool):
    """GET /jobs/{id} for a UUID that was never inserted is 404."""
    access_token, _ = await _create_user_with_tokens("queue-missing@example.com", "StrongPass123")
    response = await client.get(
        "/jobs/00000000-0000-0000-0000-000000000001",
        headers=_bearer(access_token),
    )
    assert response.status_code == 404
