"""FastAPI dependencies: extract + verify the bearer token, load the user, and enforce role guards."""

import uuid  # the JWT "sub" claim is parsed back into a UUID to look the user up

import jwt  # catches PyJWT's decode errors (bad signature, expired, wrong type) as a single family
from fastapi import Depends, HTTPException, status  # DI + the HTTP error this layer raises on auth failure
from fastapi.security import OAuth2PasswordBearer  # extracts the `Authorization: Bearer <token>` header
from sqlalchemy.ext.asyncio import AsyncSession  # type of the DB session dependency below

from app.auth.security import decode_access_token  # verifies signature/expiry/type of the access token
from app.core.config import Settings, get_settings  # cached settings, needed for the JWT secret/algorithm
from app.core.db import get_db_session  # yields a request-scoped AsyncSession
from app.models.enums import UserRole  # role comparison target for the guards below
from app.models.user import User  # the ORM row returned to route handlers

# tokenUrl is only used to populate OpenAPI's "Authorize" button in the docs UI; it doesn't affect
# runtime behavior since we validate the token ourselves rather than delegating to this scheme.
_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


async def get_current_user(
    token: str | None = Depends(_oauth2_scheme),
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> User:
    """Resolve the caller's `User` row from a bearer access token, or raise HTTP 401."""
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if token is None:
        raise credentials_error

    try:
        payload = decode_access_token(token, settings=settings)
        user_id = uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        # KeyError: missing "sub" claim. ValueError: "sub" isn't a valid UUID. Both are malformed
        # tokens, not distinguishable from "invalid signature" as far as the client response goes.
        raise credentials_error from exc

    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise credentials_error
    return user


def require_recruiter(user: User = Depends(get_current_user)) -> User:
    """Route dependency: only recruiters (admin or not) may proceed; candidates get HTTP 403."""
    if user.role != UserRole.RECRUITER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="recruiter role required")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    """Route dependency: only recruiters with `is_admin=True` may proceed; everyone else gets HTTP 403."""
    if user.role != UserRole.RECRUITER or not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin privileges required")
    return user
