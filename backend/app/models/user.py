"""The `users` table: candidates and recruiters share one table, distinguished by `role`."""

from sqlalchemy import Boolean, Enum, String  # column types: booleans, native Postgres enum, variable-length text
from sqlalchemy.orm import Mapped, mapped_column, relationship  # typed columns + ORM relationship declarations

from app.core.db import Base  # declarative base shared by every model so Alembic autogenerate sees them all
from app.models.enums import UserRole  # the candidate/recruiter role enum stored in this table
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin  # shared id + created_at/updated_at columns


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A registered account: either a candidate or a recruiter (admin is a flag on recruiters)."""

    __tablename__ = "users"  # actual Postgres table name this class maps to

    # unique=True both enforces one account per address and gives us a fast lookup index for login.
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    # Argon2id hash string (includes algorithm/params/salt inline); raw passwords are never stored.
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    # Optional display name shown in the UI; not required at registration to keep the form short.
    full_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # native_enum=True creates a real Postgres ENUM type ("userrole") rather than a plain varchar + check.
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role", native_enum=True), nullable=False, default=UserRole.CANDIDATE
    )
    # Only meaningful when role == RECRUITER; a candidate with is_admin=True has no elevated access anywhere.
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Soft-disable switch: lets us lock an account (e.g. abuse, offboarding) without deleting its history.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # One user can hold many refresh tokens over time (one per device/session); cascade deletes them with the user.
    # "RefreshToken" is a forward-reference string: SQLAlchemy resolves it against its shared declarative
    # registry once all model modules have been imported (see app/models/__init__.py), so this file never
    # needs to import refresh_token.py directly and risk a circular import.
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(  # noqa: F821 - resolved via registry, not import
        back_populates="user", cascade="all, delete-orphan"
    )
