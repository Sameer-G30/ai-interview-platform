"""Shared pytest fixtures: an in-process HTTP client and automatic per-test DB cleanup.

These tests run against the real Docker Postgres (see docker-compose.yml / CI's service containers),
not a mock - the plan's verification rules call for exercising Alembic + the live DB, not an SQLite
stand-in that would let subtle Postgres-only behavior (enum types, cascades) slip through untested.
"""

import pytest  # pytest.fixture decorator and the fixture machinery itself
from httpx import ASGITransport, AsyncClient  # in-process HTTP client, no real network/port needed

from app.core.db import AsyncSessionLocal, engine  # session factory + the shared engine's connection pool
from app.main import app  # the FastAPI app under test
from app.models.answer import Answer  # each model imported explicitly so cleanup can target its table
from app.models.async_job import AsyncJob
from app.models.interview_session import InterviewSession
from app.models.job import Job
from app.models.refresh_token import RefreshToken
from app.models.resume import Resume
from app.models.score import Score
from app.models.user import User

# Deletion order matters: children (FK-dependent tables) before the parents they reference, so no
# FK constraint violation occurs even though every FK here is already ON DELETE CASCADE/SET NULL.
_TABLES_CHILD_TO_PARENT = [Score, Answer, InterviewSession, Resume, AsyncJob, Job, RefreshToken, User]


@pytest.fixture
async def client():
    """An httpx AsyncClient that calls the FastAPI app in-process via ASGI, not over a real socket."""
    transport = ASGITransport(app=app)
    # base_url is required by httpx's API even though no real network call ever happens.
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client


@pytest.fixture(autouse=True)
async def _clean_database_and_dispose_engine():
    """After each test: truncate every domain table, then drop every pooled DB connection.

    Both steps run in this single fixture (rather than two separate ones) so the ordering between
    them is guaranteed: cleanup must happen *before* disposal, using the connections that are still
    valid in this test's event loop.

    Cleanup: truncates every table so tests never observe each other's rows (autouse means every
    test gets this without opting in explicitly).

    Disposal: each test function runs on its own fresh asyncio event loop (pytest-asyncio's
    function-scoped default), but `app.core.db.engine`'s connection pool is a single module-level
    object created once at import time. Without disposing it here, a connection opened while test A's
    loop was running would get handed back out during test B (a different loop) and asyncpg raises
    "Future attached to a different loop". Disposing forces the pool to open brand-new connections on
    next use, in whatever loop is current at that point.
    """
    yield  # run the test first
    async with AsyncSessionLocal() as session:
        for model in _TABLES_CHILD_TO_PARENT:
            await session.execute(model.__table__.delete())
        await session.commit()
    await engine.dispose()
