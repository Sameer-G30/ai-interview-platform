"""Pydantic request/response models for the `/jobs/*` endpoints."""

import uuid  # job ids and user ids are UUIDs
from datetime import datetime  # created_at / updated_at on the poll payload
from typing import Any  # JSON payload/result are untyped dicts at this layer

from pydantic import BaseModel, Field  # request/response models + constraints on the demo body

from app.models.enums import AsyncJobStatus  # queued / running / succeeded / failed as JSON strings


class DemoJobRequest(BaseModel):
    """Body for `POST /jobs/demo`. Throwaway Phase 4 contract so the queue is testable without ml/."""

    message: str = Field(default="hello from the queue", max_length=200)  # echoed in result.echo on success
    sleep_ms: int = Field(default=0, ge=0, le=5000)  # optional delay so the SPA can show running
    fail: bool = False  # tests set true to cover FAILED; the SPA demo always sends false/omits this


class AsyncJobOut(BaseModel):
    """Public job-status payload returned by enqueue and by `GET /jobs/{id}`."""

    model_config = {"from_attributes": True}  # built from a SQLAlchemy AsyncJob instance

    id: uuid.UUID  # poll this via GET /jobs/{id}
    job_type: str  # e.g. demo_echo; later resume_parse / transcribe / evaluate
    status: AsyncJobStatus  # serializes as "queued" | "running" | "succeeded" | "failed"
    user_id: uuid.UUID | None  # owner; GET hides rows that do not belong to the caller
    payload: dict[str, Any] | None  # input the worker received
    result: dict[str, Any] | None  # output once succeeded; null otherwise
    error: str | None  # short failure summary once failed; null otherwise
    created_at: datetime  # row insert time
    updated_at: datetime  # last status write (running / terminal)
