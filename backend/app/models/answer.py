"""The `answers` table: one question/answer pair within an interview session."""

import uuid  # FK columns reference InterviewSession.id

from sqlalchemy import ForeignKey, Integer, String, Text, Uuid  # column types used below
from sqlalchemy.orm import Mapped, mapped_column, relationship  # typed columns + relationship declarations

from app.core.db import Base  # shared declarative base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin  # id + created_at/updated_at columns


class Answer(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A single question posed to the candidate plus their response. Transcript/audio columns exist now
    so the speech-pipeline phase can populate them without another migration touching this table."""

    __tablename__ = "answers"

    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("interview_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # 0-based position within the session, used to render/replay questions in the order they were asked.
    question_order: Mapped[int] = mapped_column(Integer, nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    # Direct text answer, populated when the candidate types instead of (or in addition to) speaking.
    answer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Path under Settings.storage_root to the recorded audio blob, set once MediaRecorder upload lands.
    audio_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Whisper transcript of audio_path, filled in by the speech-pipeline phase's transcribe worker.
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Back-reference to the parent session.
    session: Mapped["InterviewSession"] = relationship(back_populates="answers")  # noqa: F821
