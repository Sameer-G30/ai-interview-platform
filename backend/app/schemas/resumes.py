"""Pydantic response models for the `/resumes/*` endpoints."""

import uuid  # resume ids, async job ids
from datetime import datetime  # created_at / updated_at on the results payload
from typing import Any  # parsed_data shape depends on ml.resume's output, untyped at this layer

from pydantic import BaseModel  # response models; upload is multipart, not JSON, so no request model needed here

from app.models.enums import ResumeStatus  # uploaded / processing / parsed / failed as JSON strings


class ResumeUploadOut(BaseModel):
    """Returned immediately by `POST /resumes`, before any parsing has happened."""

    resume_id: uuid.UUID  # poll results via GET /resumes/{resume_id}
    async_job_id: uuid.UUID  # poll parse progress via the existing GET /jobs/{id}
    status: ResumeStatus  # "uploaded" at this point; the worker advances it to processing/parsed/failed


class ResumeOut(BaseModel):
    """Full resume record returned by `GET /resumes/{resume_id}`, owner-only."""

    model_config = {"from_attributes": True}  # built from a SQLAlchemy Resume instance

    id: uuid.UUID
    original_filename: str  # candidate's filename, for display
    status: ResumeStatus  # serializes as "uploaded" | "processing" | "parsed" | "failed"
    parsed_data: dict[str, Any] | None  # sections/skills/contact/ats_breakdown once status == parsed
    ats_score: float | None  # 0-100 once status == parsed; null otherwise
    created_at: datetime
    updated_at: datetime
