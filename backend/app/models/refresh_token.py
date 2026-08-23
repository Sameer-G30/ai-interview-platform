"""The `refresh_tokens` table: backs rotate-on-use refresh tokens with reuse detection."""

import uuid  # typed FK columns reference User.id, which is a uuid.UUID
from datetime import datetime  # Python-side type for the timestamp columns declared below

from sqlalchemy import DateTime, ForeignKey, String, Uuid  # column types + FK constraint builder
from sqlalchemy.orm import Mapped, mapped_column, relationship  # typed columns + the back_populates relationship

from app.core.db import Base  # shared declarative base
from app.models.mixins import UUIDPrimaryKeyMixin  # id column only; this table intentionally has no updated_at

# (a refresh token is either revoked or not - there's no in-place "update" concept worth tracking).


class RefreshToken(UUIDPrimaryKeyMixin, Base):
    """One issued refresh token. Using this while `revoked_at` is set means the token was replayed."""

    __tablename__ = "refresh_tokens"

    # ondelete="CASCADE" mirrors the ORM-level cascade on User.refresh_tokens for the case of raw SQL deletes.
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # We store only a SHA-256 hex digest of the raw refresh token, never the token itself - if the
    # `refresh_tokens` table leaks, the tokens inside it are useless without the original random value.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    # When this token was created, used purely for auditing/debugging (created_at from a mixin would
    # duplicate this, so this table defines it directly instead of pulling in TimestampMixin).
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Hard expiry independent of revocation; checked on every refresh even if never explicitly revoked.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # NULL means still valid; set the moment it is used (rotated) or the user logs out.
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Self-referential pointer to the token that replaced this one on rotation. If a client ever
    # presents a token that already has replaced_by_id set, that's reuse of a stolen/rotated token -
    # the auth service treats it as a signal to revoke the *entire* chain for that user.
    replaced_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("refresh_tokens.id", ondelete="SET NULL"), nullable=True
    )

    # Back-reference to the owning user; population happens via User.refresh_tokens' back_populates.
    user: Mapped["User"] = relationship(back_populates="refresh_tokens")  # noqa: F821
