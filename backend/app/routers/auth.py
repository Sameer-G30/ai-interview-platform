"""`/auth/*` endpoints: register, login, refresh, logout. Rate-limited per client IP via slowapi."""

from fastapi import APIRouter, Depends, HTTPException, Request, status  # routing/DI/error primitives
from sqlalchemy.ext.asyncio import AsyncSession  # request-scoped DB session type

from app.auth import service  # register_user/authenticate_user/issue_token_pair/rotate/revoke logic
from app.auth.dependencies import get_current_user  # resolves the caller's User from a bearer token
from app.auth.exceptions import (
    EmailAlreadyRegisteredError,  # -> 409 on register
    InactiveUserError,  # -> 401 on login for a deactivated account
    InvalidCredentialsError,  # -> 401 on login
    InvalidRefreshTokenError,  # -> 401 on refresh/logout
    RefreshTokenReusedError,  # -> 401 on refresh (treated identically to InvalidRefreshTokenError)
)
from app.core.config import Settings, get_settings  # JWT/refresh expiry config, injected per request
from app.core.db import get_db_session  # yields the request-scoped AsyncSession
from app.core.rate_limit import limiter  # shared slowapi Limiter instance
from app.models.user import User  # type of the authenticated dependency's return value
from app.schemas.auth import (
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    TokenPairResponse,
    UserOut,
)

# A dedicated prefix keeps every route here under /auth/... without repeating it on each decorator.
router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenPairResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")  # registration abuse (mass account creation) is throttled tighter than default
async def register(
    request: Request,  # required (unused directly) so slowapi's decorator can read the client's address
    body: RegisterRequest,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> TokenPairResponse:
    """Create a new account and immediately log it in, returning an access + refresh token pair."""
    try:
        user = await service.register_user(
            session, email=body.email, password=body.password, full_name=body.full_name, role=body.role
        )
    except EmailAlreadyRegisteredError as exc:
        # Roll back the failed attempt's partial state (none expected here, but keeps the session clean).
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    access_token, refresh_token = await service.issue_token_pair(session, user=user, settings=settings)
    await session.commit()
    return TokenPairResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/login", response_model=TokenPairResponse)
@limiter.limit("10/minute")  # slows down brute-force password guessing against a single/rotating IP
async def login(
    request: Request,
    body: LoginRequest,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> TokenPairResponse:
    """Verify credentials and return a fresh access + refresh token pair."""
    try:
        user = await service.authenticate_user(session, email=body.email, password=body.password)
    except (InvalidCredentialsError, InactiveUserError) as exc:
        # Same status/detail shape for both: don't reveal whether an account exists vs. is disabled.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="incorrect email or password") from exc

    access_token, refresh_token = await service.issue_token_pair(session, user=user, settings=settings)
    await session.commit()
    return TokenPairResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=TokenPairResponse)
@limiter.limit("30/minute")  # higher than login/register since legitimate clients refresh frequently
async def refresh(
    request: Request,
    body: RefreshRequest,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> TokenPairResponse:
    """Rotate a refresh token: the presented token is revoked and a brand-new pair is issued."""
    try:
        access_token, new_refresh_token = await service.rotate_refresh_token(
            session, raw_refresh_token=body.refresh_token, settings=settings
        )
    except (InvalidRefreshTokenError, RefreshTokenReusedError) as exc:
        await session.commit()  # persist any revocation side-effects (e.g. reuse -> revoke-all) even on error
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid refresh token") from exc

    await session.commit()
    return TokenPairResponse(access_token=access_token, refresh_token=new_refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/minute")
async def logout(
    request: Request,
    body: LogoutRequest,
    session: AsyncSession = Depends(get_db_session),
) -> None:
    """Revoke one refresh token (ends that device/session); always succeeds, even if already invalid."""
    await service.revoke_refresh_token(session, raw_refresh_token=body.refresh_token)
    await session.commit()


@router.get("/me", response_model=UserOut)
async def read_current_user(current_user: User = Depends(get_current_user)) -> User:
    """Return the caller's own profile; exercises the bearer-token dependency end to end."""
    return current_user
