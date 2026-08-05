"""Liveness/readiness endpoint used by CI, docker healthchecks, and manual smoke testing."""

# APIRouter lets us define these routes in isolation and mount them from main.py.
from fastapi import APIRouter

# A dedicated router so main.py stays a thin composition point as more routers are added.
router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> dict[str, str]:
    """Return a trivial OK payload so uptime checks and CI don't need real dependencies."""
    # No DB/Redis calls here on purpose: this must succeed even if those are down,
    # so it can distinguish "API process is alive" from "API's dependencies are alive".
    return {"status": "ok"}
