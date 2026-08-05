"""FastAPI application entrypoint: creates the app, wires middleware and routers."""

from fastapi import FastAPI  # the ASGI framework instance we configure and expose to uvicorn
from fastapi.middleware.cors import CORSMiddleware  # lets the Vite dev server call this API cross-origin

from app.core.config import get_settings  # cached, typed Settings object read from env/.env
from app.routers import health  # health router, first of many routers mounted onto the app below

# Resolve settings once at import time so both app construction and CORS config can use them.
settings = get_settings()

# Construct the FastAPI app; title/description surface in the auto-generated OpenAPI docs.
app = FastAPI(
    title=settings.app_name,
    description="Backend API for resume parsing, interview simulation, and scoring.",
    version="0.1.0",
)

# Register CORS so the browser-based frontend (different port/origin in dev) is allowed to call us.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],  # only the configured frontend origin, not "*"
    allow_credentials=True,  # required so cookies/auth headers survive the CORS check
    allow_methods=["*"],  # permit all HTTP verbs the API defines (GET/POST/PATCH/...)
    allow_headers=["*"],  # permit all request headers, including Authorization
)

# Mount the health router at the app root so `GET /health` is reachable.
app.include_router(health.router)
