"""Auth business logic: registration, login, and refresh-token rotation with reuse detection.

Every function here takes an `AsyncSession` explicitly rather than opening its own, so callers
(routers, tests) control the transaction boundary and can share one session per request.
"""

import uuid  # refresh token lookups/inserts work with typed UUID user/session ids
from datetime import UTC, datetime, timedelta  # expiry math for refresh tokens

from sqlalchemy import select  # builds the SELECT queries used for email/token lookups
from sqlalchemy.ext.asyncio import AsyncSession  # the request-scoped DB session type every function accepts

from app.auth.exceptions import (
    EmailAlreadyRegisteredError,  # raised on duplicate registration
    InactiveUserError,  # raised when a deactivated account tries to authenticate
    InvalidCredentialsError,  # raised on unknown email / wrong password
    InvalidRefreshTokenError,  # raised on unknown/expired/revoked refresh token
    RefreshTokenReusedError,  # raised when an already-rotated token is replayed
)
from app.auth.security import (
    create_access_token,  # mints a new short-lived JWT access token
    create_refresh_token_value,  # generates a new opaque high-entropy refresh token
    hash_password,  # Argon2id hash for storing a new user's password
    hash_refresh_token,  # SHA-256 of a raw refresh token, the only form persisted
    verify_password,  # Argon2id verification against a stored hash
)
from app.core.config import Settings  # passed explicitly so tests can inject different expiry windows
from app.models.enums import UserRole  # role default/validation for registration
from app.models.refresh_token import RefreshToken  # the table rotation/reuse-detection operates on
from app.models.user import User  # the table register/authenticate operate on


async def register_user(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    full_name: str | None,
    role: UserRole,
) -> User:
    """Create a new user, hashing their password, or raise if the email is already taken."""
    # Case-insensitive uniqueness would be more correct in general, but the DB unique index on `email`
    # is case-sensitive; normalizing to lowercase here keeps app-level behavior consistent with that index.
    normalized_email = email.strip().lower()
    existing = await session.scalar(select(User).where(User.email == normalized_email))
    if existing is not None:
        raise EmailAlreadyRegisteredError(f"email already registered: {normalized_email}")

    user = User(
        email=normalized_email,
        hashed_password=hash_password(password),
        full_name=full_name,
        role=role,
        is_admin=False,  # never settable through registration; see RegisterRequest's docstring
    )
    session.add(user)
    # flush (not commit) assigns the DB-visible defaults / lets FK inserts elsewhere in the same
    # request see this row, while leaving the actual commit/rollback boundary to the router/caller.
    await session.flush()
    return user


async def authenticate_user(session: AsyncSession, *, email: str, password: str) -> User:
    """Verify credentials and return the matching active user, or raise `InvalidCredentialsError`."""
    normalized_email = email.strip().lower()
    user = await session.scalar(select(User).where(User.email == normalized_email))
    # Same error for "no such user" and "wrong password" so login responses don't leak which emails exist.
    if user is None or not verify_password(password, user.hashed_password):
        raise InvalidCredentialsError("incorrect email or password")
    if not user.is_active:
        raise InactiveUserError("this account has been deactivated")
    return user


async def issue_token_pair(session: AsyncSession, *, user: User, settings: Settings) -> tuple[str, str]:
    """Create a fresh (access_token, raw_refresh_token) pair for `user` and persist the refresh token."""
    access_token = create_access_token(user_id=user.id, settings=settings)

    raw_refresh_token = create_refresh_token_value()
    now = datetime.now(UTC)
    refresh_row = RefreshToken(
        user_id=user.id,
        token_hash=hash_refresh_token(raw_refresh_token),
        created_at=now,
        expires_at=now + timedelta(days=settings.refresh_token_expire_days),
    )
    session.add(refresh_row)
    await session.flush()
    return access_token, raw_refresh_token


async def _get_valid_refresh_token_row(session: AsyncSession, *, raw_refresh_token: str) -> RefreshToken:
    """Look up a refresh token row by hash and enforce the reuse-detection + expiry rules.

    Shared by `rotate_refresh_token` and `revoke_refresh_token` so both paths apply identical checks.
    """
    token_hash = hash_refresh_token(raw_refresh_token)
    row = await session.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    if row is None:
        raise InvalidRefreshTokenError("refresh token not recognized")

    if row.replaced_by_id is not None:
        # This exact token was already rotated once before - presenting it again means either the
        # legitimate client retried after losing the response, or (more dangerously) an attacker is
        # replaying a stolen token. We can't distinguish those cases, so we treat it as theft: revoke
        # every refresh token this user currently holds, forcing a fresh login everywhere.
        await _revoke_all_tokens_for_user(session, user_id=row.user_id)
        raise RefreshTokenReusedError("refresh token was already used; all sessions revoked")

    now = datetime.now(UTC)
    if row.revoked_at is not None or row.expires_at <= now:
        raise InvalidRefreshTokenError("refresh token expired or revoked")

    return row


async def _revoke_all_tokens_for_user(session: AsyncSession, *, user_id: uuid.UUID) -> None:
    """Mark every currently-valid refresh token for a user as revoked (used on reuse detection)."""
    now = datetime.now(UTC)
    result = await session.scalars(
        select(RefreshToken).where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
    )
    for token_row in result:
        token_row.revoked_at = now
    await session.flush()


async def rotate_refresh_token(
    session: AsyncSession, *, raw_refresh_token: str, settings: Settings
) -> tuple[str, str]:
    """Validate a refresh token, revoke it, issue a new (access_token, refresh_token) pair, and link
    the rotation chain via `replaced_by_id` so a later replay of the old token is detected as reuse."""
    old_row = await _get_valid_refresh_token_row(session, raw_refresh_token=raw_refresh_token)
    user = await session.get(User, old_row.user_id)
    if user is None or not user.is_active:
        # The user row was deleted or deactivated since this refresh token was issued.
        raise InvalidRefreshTokenError("account no longer available")

    access_token, new_raw_refresh_token = await issue_token_pair(session, user=user, settings=settings)

    # Look the brand-new row back up (issue_token_pair only returns the raw value, not the ORM row)
    # so we can link old_row -> new_row and mark old_row revoked in the same rotation step.
    new_token_hash = hash_refresh_token(new_raw_refresh_token)
    new_row = await session.scalar(select(RefreshToken).where(RefreshToken.token_hash == new_token_hash))
    old_row.revoked_at = datetime.now(UTC)
    old_row.replaced_by_id = new_row.id
    await session.flush()

    return access_token, new_raw_refresh_token


async def revoke_refresh_token(session: AsyncSession, *, raw_refresh_token: str) -> None:
    """Revoke a single refresh token (logout for one device/session), idempotently.

    Unlike rotation, logout on an already-invalid token is not an error worth surfacing - the end
    state (token unusable) is what the caller wanted either way.
    """
    token_hash = hash_refresh_token(raw_refresh_token)
    row = await session.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    if row is None:
        return
    row.revoked_at = datetime.now(UTC)
    await session.flush()
