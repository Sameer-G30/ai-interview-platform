"""Integration tests for register/login/refresh/logout against the real Docker Postgres.

Setup for tests that need an *already-registered* user goes through `app.auth.service` directly
(not the rate-limited HTTP endpoint) so the suite stays fast and never risks tripping slowapi's
per-route limits just from fixture setup; the `/auth/register` endpoint itself is still exercised
end to end by the two register-specific tests below.
"""

from app.auth import service  # register_user/issue_token_pair, called directly for test setup
from app.core.config import get_settings  # same Settings the app itself uses, for token expiry config
from app.core.db import AsyncSessionLocal  # opens a session identical to what the app's DI would hand out
from app.models.enums import UserRole  # role passed to register_user

settings = get_settings()


async def _create_user_with_tokens(email: str, password: str) -> tuple[str, str]:
    """Register a user directly via the service layer and return (access_token, refresh_token)."""
    async with AsyncSessionLocal() as session:
        user = await service.register_user(
            session, email=email, password=password, full_name="Test User", role=UserRole.CANDIDATE
        )
        access_token, refresh_token = await service.issue_token_pair(session, user=user, settings=settings)
        await session.commit()
    return access_token, refresh_token


async def test_register_returns_a_token_pair(client):
    """POST /auth/register creates the account and immediately returns usable access+refresh tokens."""
    response = await client.post(
        "/auth/register",
        json={"email": "new-candidate@example.com", "password": "StrongPass123", "full_name": "New Candidate"},
    )
    assert response.status_code == 201
    body = response.json()
    # Both tokens must be present and non-empty; their *validity* is exercised by the other tests below.
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["token_type"] == "bearer"


async def test_register_duplicate_email_is_rejected(client):
    """A second registration with the same email must fail with 409, not silently overwrite the account."""
    payload = {"email": "duplicate@example.com", "password": "StrongPass123"}
    first = await client.post("/auth/register", json=payload)
    assert first.status_code == 201

    second = await client.post("/auth/register", json=payload)
    assert second.status_code == 409


async def test_login_succeeds_with_correct_credentials(client):
    """POST /auth/login returns a fresh token pair for a previously-registered user."""
    await _create_user_with_tokens("login-ok@example.com", "StrongPass123")

    response = await client.post("/auth/login", json={"email": "login-ok@example.com", "password": "StrongPass123"})
    assert response.status_code == 200
    assert response.json()["access_token"]


async def test_login_fails_with_wrong_password(client):
    """A wrong password must be rejected with 401, and the message must not reveal whether the email exists."""
    await _create_user_with_tokens("login-bad@example.com", "StrongPass123")

    response = await client.post("/auth/login", json={"email": "login-bad@example.com", "password": "WrongPass1"})
    assert response.status_code == 401


async def test_login_fails_for_unknown_email(client):
    """An email with no account must get the exact same 401 shape as a wrong password, per service.py's design."""
    response = await client.post("/auth/login", json={"email": "nobody@example.com", "password": "whatever123"})
    assert response.status_code == 401


async def test_refresh_rotates_the_token_and_invalidates_the_old_one(client):
    """Using a refresh token issues a new pair, and the old refresh token must stop working afterward."""
    _, refresh_token = await _create_user_with_tokens("refresh-rotate@example.com", "StrongPass123")

    first_refresh = await client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert first_refresh.status_code == 200
    new_refresh_token = first_refresh.json()["refresh_token"]
    assert new_refresh_token != refresh_token  # rotation must produce a genuinely new value

    # The original token was consumed by the rotation above; presenting it again must now fail.
    second_use_of_old_token = await client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert second_use_of_old_token.status_code == 401


async def test_refresh_reuse_of_a_rotated_token_revokes_the_whole_chain(client):
    """Replaying an already-rotated refresh token is treated as theft: even the *newest* token in the
    chain gets revoked as a side effect, forcing the user to log in again everywhere."""
    _, refresh_token = await _create_user_with_tokens("refresh-reuse@example.com", "StrongPass123")

    first_rotation = await client.post("/auth/refresh", json={"refresh_token": refresh_token})
    new_refresh_token = first_rotation.json()["refresh_token"]

    # Replay the already-rotated original token - this should be rejected AND revoke the new one too.
    reuse_attempt = await client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert reuse_attempt.status_code == 401

    # The token issued by the legitimate rotation is now also unusable, because reuse revokes the chain.
    attempt_with_newer_token = await client.post("/auth/refresh", json={"refresh_token": new_refresh_token})
    assert attempt_with_newer_token.status_code == 401


async def test_logout_revokes_the_refresh_token(client):
    """POST /auth/logout must make the given refresh token unusable for future refresh calls."""
    _, refresh_token = await _create_user_with_tokens("logout@example.com", "StrongPass123")

    logout_response = await client.post("/auth/logout", json={"refresh_token": refresh_token})
    assert logout_response.status_code == 204

    refresh_after_logout = await client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert refresh_after_logout.status_code == 401


async def test_logout_is_idempotent_for_an_already_invalid_token(client):
    """Logging out with a token that was never valid still returns 204 - logout's goal state doesn't
    depend on the token's prior validity, only on it being unusable afterward, which it already is."""
    response = await client.post("/auth/logout", json={"refresh_token": "not-a-real-refresh-token"})
    assert response.status_code == 204


async def test_me_requires_a_bearer_token(client):
    """GET /auth/me with no Authorization header must be rejected with 401."""
    response = await client.get("/auth/me")
    assert response.status_code == 401


async def test_me_returns_the_authenticated_user(client):
    """GET /auth/me with a valid access token returns that user's own (non-sensitive) profile."""
    access_token, _ = await _create_user_with_tokens("me@example.com", "StrongPass123")

    response = await client.get("/auth/me", headers={"Authorization": f"Bearer {access_token}"})
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "me@example.com"
    assert body["role"] == "candidate"
    # The response must never leak the password hash - UserOut simply has no such field.
    assert "hashed_password" not in body
