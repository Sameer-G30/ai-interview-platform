"""Shared slowapi `Limiter` instance, keyed by client IP, applied to the auth endpoints."""

from slowapi import Limiter  # per-route rate limiting middleware
from slowapi.util import get_remote_address  # default key function: limits are tracked per client IP

from app.core.config import get_settings  # cached Settings, source of the default limit string

settings = get_settings()

# One process-wide Limiter, imported by both main.py (to register the middleware/exception handler)
# and app.routers.auth (to decorate individual endpoints with `@limiter.limit(...)`).
limiter = Limiter(key_func=get_remote_address, default_limits=[settings.rate_limit_default])
