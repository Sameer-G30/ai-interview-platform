"""The `scores` table: one composite score row per interview session, with per-signal attribution."""

import uuid  # FK column references InterviewSession.id

from sqlalchemy import JSON, Float, ForeignKey, Uuid  # column types used below
from sqlalchemy.orm import Mapped, mapped_column, relationship  # typed columns + relationship declarations

from app.core.db import Base  # shared declarative base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin  # id + created_at/updated_at columns


class Score(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Composite + per-signal scores for one session. All score columns are nullable because they're
    populated incrementally by later phases (resume score at upload time, technical/behavioral/comm
    at scoring time); `attribution` persists the weight breakdown per Part 4 of the plan so composite
    scores stay explainable even after `ml/scoring/weights.py` config changes later."""

    __tablename__ = "scores"

    # unique=True: exactly one composite score row per session, matching the plan's "aggregation" step.
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("interview_sessions.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    resume_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    technical_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    communication_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    behavioral_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    composite_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # e.g. {"resume": {"weight": 0.2, "value": 78.0, "contribution": 15.6}, ...} - reconstructable explanation
    # for EU AI Act Article 86-style transparency, and swappable inputs for the research plan's weight sweep.
    attribution: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Back-reference to the parent session.
    session: Mapped["InterviewSession"] = relationship(back_populates="score")  # noqa: F821
