"""Pydantic request/response models for the `/auth/*` endpoints."""

import uuid  # user ids are UUIDs in responses

from pydantic import BaseModel, EmailStr, Field  # base model + validated email type + field constraints

from app.models.enums import UserRole  # reused so the API and DB agree on the set of valid roles


class RegisterRequest(BaseModel):
    """Body for `POST /auth/register`."""

    email: EmailStr  # validated at the schema layer before it ever reaches the DB unique constraint
    # min_length=8 is a baseline; Argon2id itself doesn't need a strength check, but weak passwords
    # still deserve rejecting before we bother hashing them.
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=200)
    # Registration only ever creates a candidate or a plain recruiter - is_admin can never be set
    # through this endpoint; granting admin is an operator/ops action, not self-service.
    role: UserRole = UserRole.CANDIDATE


class LoginRequest(BaseModel):
    """Body for `POST /auth/login`."""

    email: EmailStr
    password: str = Field(min_length=1, max_length=128)  # no min_length=8 here: don't leak policy on login


class RefreshRequest(BaseModel):
    """Body for `POST /auth/refresh`."""

    refresh_token: str  # the raw refresh token issued at login/register or by a previous refresh call


class LogoutRequest(BaseModel):
    """Body for `POST /auth/logout`."""

    refresh_token: str  # the specific refresh token (session/device) being revoked


class TokenPairResponse(BaseModel):
    """Returned by register/login/refresh: a fresh access + refresh token pair."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # matches the `Authorization: Bearer <token>` convention FastAPI/OpenAPI expect


class UserOut(BaseModel):
    """Public-safe user representation; never includes `hashed_password`."""

    # from_attributes=True lets this model be built directly from a SQLAlchemy `User` ORM instance.
    model_config = {"from_attributes": True}

    id: uuid.UUID
    email: EmailStr
    full_name: str | None
    role: UserRole
    is_admin: bool
    is_active: bool
