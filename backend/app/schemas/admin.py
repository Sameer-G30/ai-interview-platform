"""Pydantic contracts for `/admin/*` user, posting, session, and score listing.

Admin listing is a read of stored rows (plus PATCH `is_active` / recruiter-only `is_admin`).
It does not recompute composites, call Ollama, or enqueue ARQ jobs.
"""

import uuid  # user / posting / session ids in JSON
from datetime import datetime  # created_at / completed_at on list rows
from typing import Any  # Score.attribution JSON

from pydantic import BaseModel  # request/response models

from app.models.enums import InterviewSessionStatus  # session status echoed on the audit list
from app.models.job import Job  # source ORM for AdminPostingOut.from_job
from app.models.user import User  # recruiter email on a posting row


class AdminUserPatch(BaseModel):
    """Body for `PATCH /admin/users/{id}`. Soft-disable via `is_active`; `is_admin` is recruiters only."""

    is_active: bool | None = None  # None means "leave unchanged"; False is the preferred disable
    is_admin: bool | None = None  # None means "leave unchanged"; True on a candidate is 422 in the router


class AdminPostingOut(BaseModel):
    """One posting across every recruiter. Recruiter GET /postings stays own-only; this is the ops list."""

    model_config = {"from_attributes": True}  # built from a SQLAlchemy Job plus the owning User

    id: uuid.UUID  # jobs.id
    recruiter_id: uuid.UUID  # users.id of the posting owner
    recruiter_email: str  # so the admin table is identifiable without a second GET
    title: str  # Job.title
    description: str  # Job.description
    required_skills: str | None  # freeform; unused by admin listing besides display
    is_active: bool  # PATCH target; prefer this over hard DELETE
    has_embedding: bool  # derived: True once posting_embed wrote Job.embedding
    created_at: datetime  # row insert
    updated_at: datetime  # last write

    @staticmethod
    def from_job(job: Job, recruiter: User) -> "AdminPostingOut":
        """Map one Job + owning User onto the admin posting contract (embedding stays out of JSON)."""
        return AdminPostingOut(
            id=job.id,  # posting UUID
            recruiter_id=recruiter.id,  # owner
            recruiter_email=recruiter.email,  # display
            title=job.title,  # display
            description=job.description,  # display
            required_skills=job.required_skills,  # display
            is_active=job.is_active,  # PATCH target
            has_embedding=job.embedding is not None,  # same derivation as PostingOut
            created_at=job.created_at,  # sort key on the list
            updated_at=job.updated_at,  # last write
        )


class AdminSessionListItemOut(BaseModel):
    """One interview session for ops audit. Practice (`job_id` null) is included — this is not ranking."""

    id: uuid.UUID  # interview_sessions.id
    candidate_user_id: uuid.UUID  # interview_sessions.user_id
    candidate_email: str  # users.email so the table is identifiable
    resume_id: uuid.UUID  # parsed resume this session was generated from
    job_id: uuid.UUID | None  # posting id; null means practice (still listed for admin)
    posting_title: str | None  # Job.title when job_id is set; null for practice
    status: InterviewSessionStatus  # scheduled | in_progress | completed | abandoned
    started_at: datetime | None  # set when generated questions are persisted
    completed_at: datetime | None  # set when evaluate flips the session to completed
    created_at: datetime  # list is newest first
    updated_at: datetime  # last write
    composite_score: float | None  # stored Score; null until completed (GET does not recompute)


class AdminScoreListItemOut(BaseModel):
    """One stored Score row for ops. Practice sessions are included; missing signals stay JSON null."""

    session_id: uuid.UUID  # scores.session_id / interview_sessions.id
    candidate_user_id: uuid.UUID  # interview_sessions.user_id
    candidate_email: str  # users.email
    job_id: uuid.UUID | None  # null = practice (admin sees these; recruiter ranking does not)
    posting_title: str | None  # Job.title when job_id is set
    resume_score: float | None  # ATS 0–100 or null
    technical_score: float | None  # scaled judge mean or null
    communication_score: float | None  # mapped dual fluency or null (text-only)
    behavioral_score: float | None  # scaled judge mean or null
    composite_score: float | None  # weighted sum already stored
    attribution: dict[str, Any] | None  # reconstructable JSON
    completed_at: datetime | None  # when the session flipped to completed
