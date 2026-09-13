"""Pydantic request/response models for `/scores/*` ranking, comparison, and owner GET."""

import uuid  # session / posting / user ids
from datetime import datetime  # completed_at on ranking rows
from typing import Any  # attribution JSON

from pydantic import BaseModel, Field  # response models


class ScoreOut(BaseModel):
    """Stored Score row. Signals that were omitted this session are JSON null (not a fake 0)."""

    model_config = {"from_attributes": True}  # built from a SQLAlchemy Score instance

    session_id: uuid.UUID  # unique; one composite per completed session
    resume_score: float | None  # ATS 0–100 or null
    technical_score: float | None  # scaled judge mean or null
    communication_score: float | None  # mapped dual fluency or null (text-only)
    behavioral_score: float | None  # scaled judge mean or null
    composite_score: float | None  # weighted sum; GET 404s when this is still null
    attribution: dict[str, Any] | None  # {formula_version, omitted, signals: {weight, value, contribution}}


class RankingRowOut(BaseModel):
    """One completed session on a posting, ordered by composite_score descending."""

    rank: int  # 1-based position in this posting's list
    session_id: uuid.UUID  # GET /scores/{session_id} / GET /reports/{session_id}
    candidate_user_id: uuid.UUID  # interview_sessions.user_id
    candidate_email: str  # so curl ranking is identifiable without a dashboard
    completed_at: datetime | None  # when the session flipped to completed
    resume_score: float | None  # echo Score columns
    technical_score: float | None  # echo
    communication_score: float | None  # echo
    behavioral_score: float | None  # echo
    composite_score: float | None  # sort key
    attribution: dict[str, Any] | None  # reconstructable explanation


class RankingOut(BaseModel):
    """Recruiter ranking payload for one owned posting."""

    posting_id: uuid.UUID  # jobs.id that interview_sessions.job_id points at
    sessions: list[RankingRowOut] = Field(default_factory=list)  # empty if no completed scored sessions yet


class ComparisonOut(BaseModel):
    """Side-by-side stored scores for two or more sessions on postings the recruiter owns."""

    sessions: list[ScoreOut]  # same order as the requested session_ids (after uniqueness)
