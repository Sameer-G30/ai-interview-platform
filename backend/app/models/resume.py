"""The `resumes` table: an uploaded resume file plus (once the resume-pipeline phase lands) parsed data."""

import uuid  # FK columns reference User.id

from sqlalchemy import JSON, Enum, Float, ForeignKey, String, Uuid  # column types for status/parsed payload
from sqlalchemy.orm import Mapped, mapped_column, relationship  # typed columns + relationship declarations

from app.core.db import Base  # shared declarative base
from app.models.enums import ResumeStatus  # upload/parse lifecycle enum
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin  # id + created_at/updated_at columns


class Resume(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One resume upload belonging to a candidate. `parsed_data`/`ats_score` stay NULL until the
    resume-pipeline phase's worker fills them in; this phase only needs the upload + status shape."""

    __tablename__ = "resumes"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Path under Settings.storage_root, not a public URL - the API mediates all access to the raw file.
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    # Preserves the candidate's original filename for display, separate from the on-disk storage path.
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[ResumeStatus] = mapped_column(
        Enum(ResumeStatus, name="resume_status", native_enum=True), nullable=False, default=ResumeStatus.UPLOADED
    )
    # JSON (not JSONB-specific type) keeps this portable; Postgres still stores pydantic-encoded dicts fine.
    parsed_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ats_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Back-reference to the owning candidate.
    user: Mapped["User"] = relationship()  # noqa: F821
