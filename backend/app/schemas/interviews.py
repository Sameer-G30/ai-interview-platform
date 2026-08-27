"""Pydantic request/response models for the `/interviews/*` endpoints."""

import uuid  # session ids, answer ids, async job ids, resume/posting ids
from datetime import datetime  # created_at / updated_at / started_at / completed_at
from typing import Any  # evaluation JSON matches AnswerEvaluation but is stored as a dict

from pydantic import BaseModel, Field, computed_field  # request/response models + derived has_audio

from app.models.enums import InterviewSessionStatus  # scheduled / in_progress / completed / abandoned


class InterviewStartIn(BaseModel):
    """Body for `POST /interviews`. Both ids are optional; omitted resume_id uses the latest parsed resume."""

    resume_id: uuid.UUID | None = None  # must be owned + parsed when set; 404/409 same as GET /matches
    job_id: uuid.UUID | None = None  # optional posting; 404 if missing, 409 if inactive


class InterviewStartOut(BaseModel):
    """Returned immediately by `POST /interviews`, before question generation has run."""

    session_id: uuid.UUID  # poll results via GET /interviews/{session_id}
    async_job_id: uuid.UUID  # poll generate progress via the existing GET /jobs/{id}
    status: InterviewSessionStatus  # "scheduled" at this point; the worker advances it to in_progress


class AnswerOut(BaseModel):
    """One question/answer row inside a session GET payload."""

    model_config = {"from_attributes": True}  # built from a SQLAlchemy Answer instance

    id: uuid.UUID  # submit target: POST /interviews/{session_id}/answers/{id}
    question_order: int  # 0-based ask order, including follow-ups appended at the end
    question_text: str  # generated (or follow-up) prompt
    question_kind: str  # "technical" | "behavioral"; selects the rubric at evaluate time
    is_follow_up: bool  # True when the evaluate worker appended this row
    answer_text: str | None  # NULL until the candidate submits
    evaluation: dict[str, Any] | None  # {score, rationale, strengths, improvements} once judged
    created_at: datetime  # row insert time (question generated or follow-up appended)
    updated_at: datetime  # last write (submit / evaluation)
    # Loaded from the ORM so has_audio can be derived; never serialized (do not leak storage_root paths).
    audio_path: str | None = Field(default=None, exclude=True)

    @computed_field  # JSON key has_audio; mirrors PostingOut.has_embedding rather than exposing the blob path
    @property
    def has_audio(self) -> bool:
        """True once a Phase 10 MediaRecorder upload wrote answers.audio_path; transcript stays null until Phase 11."""
        return self.audio_path is not None and len(self.audio_path) > 0


class InterviewSessionOut(BaseModel):
    """Full session record returned by `GET /interviews/{session_id}`, owner-only."""

    model_config = {"from_attributes": True}  # built from a SQLAlchemy InterviewSession instance

    id: uuid.UUID
    resume_id: uuid.UUID  # the parsed resume this session was generated from
    job_id: uuid.UUID | None  # optional posting; null for a practice interview
    status: InterviewSessionStatus  # serializes as scheduled | in_progress | completed | abandoned
    started_at: datetime | None  # set when generated questions are persisted
    completed_at: datetime | None  # set when every current question is answered and no follow-up is added
    answers: list[AnswerOut]  # ordered by question_order via the ORM relationship
    created_at: datetime
    updated_at: datetime


class AnswerSubmitIn(BaseModel):
    """Body for `POST /interviews/{session_id}/answers/{answer_id}`. Text only; audio is Phase 10+."""

    answer_text: str = Field(min_length=1)  # empty -> 422; whitespace-only is stored and scored 0


class AnswerSubmitOut(BaseModel):
    """Returned immediately by answer submit, before evaluation has run."""

    answer_id: uuid.UUID  # the row whose evaluation the client will read after polling
    async_job_id: uuid.UUID  # poll via GET /jobs/{id}; same useJobStatus hook as resume/parse
    session_status: InterviewSessionStatus  # still in_progress until the worker completes the session


class AudioUploadOut(BaseModel):
    """Returned by `POST /interviews/{session_id}/answers/{answer_id}/audio` after the blob is on disk."""

    answer_id: uuid.UUID  # the row whose audio_path was written
    has_audio: bool  # always True on success; the SPA uses this instead of the filesystem path
