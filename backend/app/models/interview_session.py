"""The `interview_sessions` table: one candidate's attempt at an (optionally job-targeted) interview."""

import uuid  # FK columns reference User.id / Job.id
from datetime import datetime  # started_at/completed_at are nullable timestamps distinct from created_at

from sqlalchemy import DateTime, Enum, ForeignKey, Uuid  # column types used below
from sqlalchemy.orm import Mapped, mapped_column, relationship  # typed columns + relationship declarations

from app.core.db import Base  # shared declarative base
from app.models.enums import InterviewSessionStatus  # session lifecycle enum
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin  # id + created_at/updated_at columns


class InterviewSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A candidate's interview run. Question generation/persistence lands in the interview-engine phase;
    this phase only needs the session shell so `answers`/`scores` have somewhere to attach."""

    __tablename__ = "interview_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Nullable: a candidate can practice generically without targeting a specific posting.
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[InterviewSessionStatus] = mapped_column(
        Enum(InterviewSessionStatus, name="interview_session_status", native_enum=True),
        nullable=False,
        default=InterviewSessionStatus.SCHEDULED,
    )
    # Set when the candidate answers the first question; distinct from created_at (row creation time).
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set when status transitions to COMPLETED; scoring can only run once this is non-NULL.
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Back-references; no cascade delete-orphan here because answers/scores manage their own cascade
    # from their own FK's ondelete="CASCADE" rather than through the ORM relationship.
    user: Mapped["User"] = relationship()  # noqa: F821
    job: Mapped["Job | None"] = relationship()  # noqa: F821
    answers: Mapped[list["Answer"]] = relationship(back_populates="session", cascade="all, delete-orphan")  # noqa: F821
    score: Mapped["Score | None"] = relationship(back_populates="session", cascade="all, delete-orphan")  # noqa: F821
