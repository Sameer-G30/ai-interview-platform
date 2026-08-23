"""The `async_jobs` table: generic status/result tracking for every queued ML task (ARQ, later phase)."""

import uuid  # FK column references User.id; PK/other ids also use uuid.UUID

from sqlalchemy import JSON, Enum, ForeignKey, String, Text, Uuid  # column types used below
from sqlalchemy.orm import Mapped, mapped_column, relationship  # typed columns + relationship declaration

from app.core.db import Base  # shared declarative base
from app.models.enums import AsyncJobStatus  # queued/running/succeeded/failed lifecycle enum
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin  # id + created_at/updated_at columns


class AsyncJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One row per background task (resume parse, transcription, LLM evaluation, ...). The API writes
    this row with status=QUEUED before enqueuing to Redis, then returns its id so the frontend can poll
    `GET /jobs/{id}` (added in the queue-infrastructure phase) instead of blocking on the HTTP request."""

    __tablename__ = "async_jobs"

    # Discriminates which worker function handles this row, e.g. "resume_parse", "transcribe", "evaluate".
    # A plain string (not an enum) because new job types will be added across many later phases without
    # needing a migration each time to widen a Postgres ENUM.
    job_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    status: Mapped[AsyncJobStatus] = mapped_column(
        Enum(AsyncJobStatus, name="async_job_status", native_enum=True), nullable=False, default=AsyncJobStatus.QUEUED
    )
    # Who triggered this job, so a user can only poll/see the status of their own jobs at the API layer.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Input the worker needs (e.g. {"resume_id": "..."}); JSON keeps this generic across job types.
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Output the worker produced once status == SUCCEEDED; shape depends on job_type.
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Human-readable failure reason when status == FAILED; full tracebacks stay in worker logs, not here.
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Back-reference to the triggering user, if any.
    user: Mapped["User | None"] = relationship()  # noqa: F821
