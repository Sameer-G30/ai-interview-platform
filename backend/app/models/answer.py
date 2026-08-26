"""The `answers` table: one question/answer pair within an interview session."""

import uuid  # FK columns reference InterviewSession.id

from sqlalchemy import (  # column types + boolean server default
    JSON,
    Boolean,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship  # typed columns + relationship declarations

from app.core.db import Base  # shared declarative base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin  # id + created_at/updated_at columns


class Answer(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A single question posed to the candidate plus their response.

    Transcript/audio columns exist so the speech-pipeline phase can populate them without another
    migration; Phase 9 leaves them NULL (text answers only). `evaluation` holds the Phase 8
    `AnswerEvaluation` JSON once `interview_evaluate` succeeds.
    """

    __tablename__ = "answers"
    __table_args__ = (
        UniqueConstraint("session_id", "question_order", name="uq_answers_session_question_order"),  # one row per slot
    )

    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("interview_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # 0-based position within the session, used to render/replay questions in the order they were asked.
    question_order: Mapped[int] = mapped_column(Integer, nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    # Selects technical_answer_v1 vs behavioral_answer_v1 at evaluate time; string not a Postgres ENUM.
    question_kind: Mapped[str] = mapped_column(
        String(32), nullable=False, default="technical", server_default="technical"
    )
    # True when this row was appended by the evaluate worker's follow-up path (never chained again).
    is_follow_up: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    # Direct text answer, populated when the candidate types instead of (or in addition to) speaking.
    answer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Path under Settings.storage_root to the recorded audio blob, set once MediaRecorder upload lands.
    audio_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Whisper transcript of audio_path, filled in by the speech-pipeline phase's transcribe worker.
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    # AnswerEvaluation JSON {score, rationale, strengths, improvements}; NULL until interview_evaluate succeeds.
    evaluation: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Back-reference to the parent session.
    session: Mapped["InterviewSession"] = relationship(back_populates="answers")  # noqa: F821
