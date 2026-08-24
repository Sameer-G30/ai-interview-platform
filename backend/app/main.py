"""FastAPI application entrypoint: creates the app, wires middleware and routers."""

from collections.abc import AsyncIterator  # typing for the lifespan generator
from contextlib import asynccontextmanager  # FastAPI lifespan hook for Redis pool setup/teardown

from fastapi import FastAPI  # the ASGI framework instance we configure and expose to uvicorn
from fastapi.middleware.cors import CORSMiddleware  # lets the Vite dev server call this API cross-origin
from slowapi import _rate_limit_exceeded_handler  # default handler that turns RateLimitExceeded into HTTP 429
from slowapi.errors import RateLimitExceeded  # exception slowapi raises when a limit is hit
from slowapi.middleware import SlowAPIMiddleware  # reads app.state.limiter and enforces limits per request

import app.models  # noqa: F401 - import side-effect registers every ORM model on Base.metadata
from app.core.config import get_settings  # cached, typed Settings object read from env/.env
from app.core.rate_limit import limiter  # shared Limiter instance, also imported by app.routers.auth
from app.core.redis import close_arq_pool, create_arq_pool  # ARQ Redis pool used to enqueue jobs
from app.routers import auth, health, jobs  # auth, health, and job-queue routers


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Open the ARQ Redis pool on startup and close it on shutdown (uvicorn). Tests set the pool themselves."""
    app.state.redis = await create_arq_pool()  # shared by POST /jobs/demo via request.app.state.redis
    try:
        yield  # run the application
    finally:
        await close_arq_pool(app.state.redis)  # drop connections so the process can exit cleanly


# Resolve settings once at import time so both app construction and CORS config can use them.
settings = get_settings()

# Construct the FastAPI app; title/description surface in the auto-generated OpenAPI docs.
app = FastAPI(
    title=settings.app_name,
    description="Backend API for resume parsing, interview simulation, and scoring.",
    version="0.1.0",
    lifespan=lifespan,  # connects Redis for enqueue; httpx ASGI tests do not enter this hook
)

# Register CORS so the browser-based frontend (different port/origin in dev) is allowed to call us.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins(),  # configured origin plus localhost/127.0.0.1 twin
    allow_credentials=True,  # required so cookies/auth headers survive the CORS check
    allow_methods=["*"],  # permit all HTTP verbs the API defines (GET/POST/PATCH/...)
    allow_headers=["*"],  # permit all request headers, including Authorization
)

# slowapi reads the limiter off app.state; both the middleware below and each route's `@limiter.limit(...)`
# decorator (see app/routers/auth.py) rely on this attribute existing before any request comes in.
app.state.limiter = limiter
# Translates a raised RateLimitExceeded into a proper HTTP 429 response instead of an unhandled 500.
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
# Enforces `limiter.default_limits` on every route, on top of any route-specific `@limiter.limit(...)`.
app.add_middleware(SlowAPIMiddleware)

# Mount the health router at the app root so `GET /health` is reachable.
app.include_router(health.router)
# Mount the auth router; all its routes are prefixed with /auth (see app/routers/auth.py).
app.include_router(auth.router)
# Mount the job-status router; POST /jobs/demo and GET /jobs/{id} (owner-only poll).
app.include_router(jobs.router)
