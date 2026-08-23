"""Shared column mixins so every ORM model gets a consistent primary key + timestamp shape."""

import uuid  # generates client-side UUID4 primary keys, portable across any SQL backend
from datetime import UTC, datetime  # UTC-aware timestamps stored consistently regardless of server timezone config

from sqlalchemy import DateTime, Uuid  # DateTime column type; Uuid is SQLAlchemy 2.0's cross-dialect UUID type
from sqlalchemy.orm import Mapped, mapped_column  # typed ORM column declarations (SQLAlchemy 2.0 style)


class UUIDPrimaryKeyMixin:
    """Gives a model a UUID primary key generated in Python before the INSERT, not by the DB."""

    # as_uuid=True maps this to Python's uuid.UUID (not str) on both sides of the ORM boundary.
    # default=uuid.uuid4 means every new row gets an id assigned immediately, even before flush,
    # which lets us reference `new_row.id` (e.g. for a refresh token's user_id) pre-commit.
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    """Adds created_at/updated_at columns maintained automatically by the ORM layer."""

    # server_default=func.now() would drift from application-level `default=` if reads/writes disagree,
    # so we set both created_at and updated_at from Python's UTC clock for consistency across the app.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    # onupdate re-evaluates the same lambda on every UPDATE issued through the ORM (not raw SQL).
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )
