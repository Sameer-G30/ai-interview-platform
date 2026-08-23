"""Low-level cryptographic primitives: Argon2id password hashing and PyJWT access/refresh tokens.

Nothing in this file touches the database - it's pure functions over strings/dicts so `service.py`
(which does touch the DB) stays easy to test/reason about separately from the crypto itself.
"""

import hashlib  # sha256 for hashing raw refresh tokens before they're stored (see hash_refresh_token)
import secrets  # cryptographically secure random token generation for refresh tokens
import uuid  # subject/user ids are UUIDs; embedded in JWT claims as strings
from datetime import UTC, datetime, timedelta  # UTC-aware expiry math for exp/iat claims
from enum import Enum  # distinguishes access vs refresh tokens inside the JWT payload itself

import jwt  # PyJWT: encodes/decodes/verifies the signed tokens
from argon2 import PasswordHasher  # Argon2id hashing/verification (argon2-cffi's high-level wrapper)
from argon2.exceptions import VerifyMismatchError  # raised by ph.verify() on a wrong password

from app.core.config import Settings  # typed settings passed in explicitly, not re-fetched here, for testability

# A single module-level PasswordHasher using argon2-cffi's defaults, which are already Argon2id with
# OWASP-recommended parameters (time_cost, memory_cost, parallelism). No need to hand-tune these.
_password_hasher = PasswordHasher()


class TokenType(str, Enum):
    """Embedded in the JWT's `type` claim so a stolen access token can't be replayed as a refresh token."""

    ACCESS = "access"
    REFRESH = "refresh"


def hash_password(raw_password: str) -> str:
    """Hash a plaintext password with Argon2id; store only the result."""
    # ph.hash() returns a self-describing string (algorithm + params + salt + hash), safe to store as-is.
    return _password_hasher.hash(raw_password)


def verify_password(raw_password: str, hashed_password: str) -> bool:
    """Check a plaintext password against a stored Argon2id hash without ever decoding the hash."""
    try:
        # verify() raises on mismatch rather than returning False, so we translate that into a bool here.
        _password_hasher.verify(hashed_password, raw_password)
        return True
    except VerifyMismatchError:
        return False


def create_access_token(*, user_id: uuid.UUID, settings: Settings) -> str:
    """Mint a short-lived signed access token carrying the user id as `sub`."""
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),  # JWT's standard "subject" claim; stringified since JWT claims are JSON-safe types
        "type": TokenType.ACCESS.value,
        "iat": now,  # issued-at, lets downstream tooling reason about token age
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),  # PyJWT enforces this on decode
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token_value() -> str:
    """Generate a new opaque, high-entropy refresh token value (not a JWT - just a random secret).

    Refresh tokens are deliberately *not* JWTs: they're random values whose hash is looked up in the
    `refresh_tokens` table, which is what makes server-side revocation and rotation possible. A JWT
    refresh token would be valid until expiry no matter what the DB says.
    """
    # 32 bytes of CSPRNG entropy, URL-safe encoded; token_urlsafe already base64-encodes internally.
    return secrets.token_urlsafe(32)


def hash_refresh_token(raw_refresh_token: str) -> str:
    """SHA-256 hex digest of a raw refresh token, the only form ever persisted to the DB."""
    return hashlib.sha256(raw_refresh_token.encode("utf-8")).hexdigest()


def decode_access_token(token: str, *, settings: Settings) -> dict:
    """Verify signature + expiry and return the decoded claims of an access token.

    Raises `jwt.PyJWTError` (or a subclass, e.g. `ExpiredSignatureError`) on any failure; callers
    (the `get_current_user` dependency) translate that into an HTTP 401.
    """
    payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    if payload.get("type") != TokenType.ACCESS.value:
        # A refresh token, structurally valid but wrong `type`, must never authenticate a request.
        raise jwt.InvalidTokenError("expected an access token")
    return payload
