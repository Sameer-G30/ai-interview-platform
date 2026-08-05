"""Smoke test: the FastAPI app boots and `/health` responds, without needing DB/Redis."""

# ASGITransport + AsyncClient let httpx call the FastAPI app in-process, with no real network/port.
from httpx import ASGITransport, AsyncClient

# The FastAPI app instance under test.
from app.main import app


async def test_health_check_returns_ok():
    """Hitting GET /health should return HTTP 200 and {"status": "ok"}."""
    # Wrap the app in an ASGI transport so requests never leave the process.
    transport = ASGITransport(app=app)
    # base_url is required by httpx even though no real network call happens.
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Perform the actual request against the in-process ASGI app.
        response = await client.get("/health")
    # The endpoint must always succeed regardless of DB/Redis availability.
    assert response.status_code == 200
    # The response body must match the trivial contract other tools rely on.
    assert response.json() == {"status": "ok"}
