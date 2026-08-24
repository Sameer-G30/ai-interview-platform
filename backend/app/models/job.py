"""The `jobs` table: job postings a recruiter creates and candidates get matched/interviewed against."""

import uuid  # FK columns reference User.id

from pgvector.sqlalchemy import Vector  # pgvector's SQLAlchemy column type, backs the 384-d SBERT embedding
from sqlalchemy import Boolean, ForeignKey, String, Text, Uuid  # column + constraint types used below
from sqlalchemy.orm import Mapped, mapped_column, relationship  # typed columns + relationship declarations

from app.core.db import Base  # shared declarative base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin  # id + created_at/updated_at columns


class Job(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A job posting created by a recruiter (`/postings` router) and matched against by candidates
    (`/matches` router) once `embedding` is populated by the `posting_embed` worker task."""

    __tablename__ = "jobs"

    # Only recruiters can own jobs; enforced at the service layer (role check), not by a DB constraint,
    # since the DB has no way to know a user's role without a join back to `users`.
    recruiter_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    # Freeform comma/line separated list for now; the job-matching phase formalizes this against the
    # ESCO taxonomy and may split it into a normalized skills table instead.
    required_skills: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Lets a recruiter stop accepting new interview sessions against a posting without deleting its history.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # 384-d SBERT vector over title+description+required_skills, written by the `posting_embed` worker
    # task once `POST /postings` enqueues it; NULL until that job succeeds (or if it fails/is pending).
    embedding: Mapped[list[float] | None] = mapped_column(Vector(384), nullable=True)

    # Convenience back-reference to the posting recruiter; no cascade defined here since deleting a
    # recruiter cascades from the User side (recruiter_id FK above), not from this relationship.
    recruiter: Mapped["User"] = relationship()  # noqa: F821
