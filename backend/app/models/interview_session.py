"""The `interview_sessions` table: one candidate's attempt at an (optionally job-targeted) interview."""

import uuid  # FK columns reference User.id / Job.id / Resume.id
from datetime import datetime  # started_at/completed_at are nullable timestamps distinct from created_at

from sqlalchemy import DateTime, Enum, ForeignKey, Uuid  # column types used below
from sqlalchemy.orm import Mapped, mapped_column, relationship  # typed columns + relationship declarations

from app.core.db import Base  # shared declarative base
from app.models.enums import InterviewSessionStatus  # session lifecycle enum
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin  # id + created_at/updated_at columns


class InterviewSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A candidate's interview run. Started from an owned parsed resume; optional `job_id` is a posting."""

    __tablename__ = "interview_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Required: every session is generated from one parsed resume's extracted skills (same selection as /matches).
    resume_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("resumes.id", ondelete="RESTRICT"), nullable=False, index=True
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
    # Set when generated questions are persisted (scheduled -> in_progress); distinct from created_at.
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set when status transitions to COMPLETED; scoring (Phase 12) can only run once this is non-NULL.
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Back-references; answers/scores cascade from their own FKs. Resume is RESTRICT so a resume
    # with sessions cannot disappear under an in-flight interview (we do not hard-delete resumes).
    user: Mapped["User"] = relationship()  # noqa: F821
    resume: Mapped["Resume"] = relationship()  # noqa: F821
    job: Mapped["Job | None"] = relationship()  # noqa: F821
    answers: Mapped[list["Answer"]] = relationship(  # noqa: F821
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="Answer.question_order",  # GET /interviews/{id} returns questions in ask order
    )
    score: Mapped["Score | None"] = relationship(back_populates="session", cascade="all, delete-orphan")  # noqa: F821
