"""Domain-level auth errors, raised by `service.py` and translated to HTTP responses by the router.

Keeping these as plain exceptions (not HTTPException) means `service.py` has zero FastAPI import and
stays trivially unit-testable without spinning up the app.
"""


class AuthError(Exception):
    """Base class for every auth domain error; lets routers catch broadly if they ever want to."""


class EmailAlreadyRegisteredError(AuthError):
    """Raised by `register_user` when the email already has an account."""


class InvalidCredentialsError(AuthError):
    """Raised by `authenticate_user` on unknown email or wrong password (deliberately the same error
    for both cases, so login responses don't leak which emails are registered)."""


class InactiveUserError(AuthError):
    """Raised when a correctly-authenticated user's account has been deactivated (`is_active=False`)."""


class InvalidRefreshTokenError(AuthError):
    """Raised by `refresh` / `logout` when the presented refresh token is unknown, expired, or revoked."""


class RefreshTokenReusedError(AuthError):
    """Raised when a refresh token that was already rotated (has `replaced_by_id` set) is presented
    again - a strong signal of token theft. The service reacts by revoking the user's entire token
    chain, and the router surfaces this the same way as an invalid token (401), never revealing to a
    potential attacker that reuse was specifically detected."""
