"""Pydantic request/response models for the `/postings/*` endpoints."""

import uuid  # posting ids, async job ids
from datetime import datetime  # created_at / updated_at on the response payload

from pydantic import BaseModel, Field  # request validation + response models

from app.models.job import Job  # source ORM type for PostingOut.from_job below


class PostingCreate(BaseModel):
    """Body for `POST /postings`. `required_skills` stays freeform text, matching `Job.required_skills`
    - the worker runs the same ESCO `extract_skills` over it at match time that resumes use."""

    title: str = Field(min_length=1, max_length=200)  # matches Job.title's column length
    description: str = Field(min_length=1)  # free text; Job.description is an unbounded Text column
    required_skills: str | None = Field(default=None)  # comma/line separated; optional, matches the model
    is_active: bool = Field(default=True)  # recruiters can create a posting already marked inactive


class PostingUpdate(BaseModel):
    """Body for `PATCH /postings/{id}`. Only `is_active` is mutable - no hard delete, no editing text."""

    is_active: bool


class PostingOut(BaseModel):
    """Full posting record returned by `GET /postings`, `GET /postings/{id}`, and `PATCH /postings/{id}`."""

    model_config = {"from_attributes": True}  # built from a SQLAlchemy Job instance

    id: uuid.UUID
    title: str
    description: str
    required_skills: str | None
    is_active: bool
    has_embedding: bool  # derived: True once the posting_embed worker has written Job.embedding
    created_at: datetime
    updated_at: datetime

    @staticmethod
    def from_job(job: Job) -> "PostingOut":
        """Build the response model from an ORM `Job`, deriving `has_embedding` from the raw vector column."""
        return PostingOut(
            id=job.id,
            title=job.title,
            description=job.description,
            required_skills=job.required_skills,
            is_active=job.is_active,
            has_embedding=job.embedding is not None,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )


class PostingCreateOut(BaseModel):
    """Returned by `POST /postings`: the created posting plus the id of the embedding job to poll."""

    posting: PostingOut
    async_job_id: uuid.UUID  # poll embedding progress via the existing GET /jobs/{id}
