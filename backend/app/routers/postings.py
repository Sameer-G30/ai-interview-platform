"""`/postings/*` endpoints: recruiter-only job posting CRUD (create/list/get/deactivate).

Distinct prefix from any future `/jobs/{id}` posting-detail route (today `/jobs` is only the generic
async-job status poller from the queue-infrastructure phase) - "postings" is unambiguous. Writes
enqueue `posting_embed` the same way `POST /resumes` enqueues `resume_parse`: commit the row first,
then enqueue, so the worker can never look up an uncommitted id.
"""

import uuid  # path param for GET/PATCH /postings/{posting_id}; posting_id also goes into the job payload

from arq.connections import ArqRedis  # injected Redis pool from app.state
from fastapi import APIRouter, Depends, HTTPException, Request, status  # routing / DI / errors
from sqlalchemy import select  # ordered "my postings" listing query
from sqlalchemy.ext.asyncio import AsyncSession  # request-scoped DB session

from app.auth.dependencies import require_recruiter  # write + read guard; candidates never own postings
from app.core.db import get_db_session  # yields the request-scoped AsyncSession
from app.core.rate_limit import limiter  # slowapi limiter; posting create is not free to spam either
from app.models.job import Job  # the row this router creates and reads back
from app.models.user import User  # type of the authenticated recruiter
from app.routers.jobs import get_arq_redis  # reuse the same "is the queue connected" dependency as /jobs
from app.schemas.postings import (  # request/response contracts
    PostingCreate,
    PostingCreateOut,
    PostingOut,
    PostingUpdate,
)
from app.workers.enqueue import EnqueueFailedError, enqueue_job  # insert queued async_jobs row + Redis enqueue
from app.workers.job_types import JOB_TYPE_POSTING_EMBED  # "posting_embed" string job type

router = APIRouter(prefix="/postings", tags=["postings"])  # every route here lives under /postings/...


@router.post("", response_model=PostingCreateOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("20/minute")  # posting create writes to Postgres + enqueues a job; tighter than the general default
async def create_posting(
    request: Request,  # required so slowapi can key the limit on client IP
    body: PostingCreate,
    session: AsyncSession = Depends(get_db_session),
    redis: ArqRedis = Depends(get_arq_redis),
    current_user: User = Depends(require_recruiter),
) -> PostingCreateOut:
    """Insert a posting owned by the caller, enqueue `posting_embed`, and return both immediately."""
    job = Job(
        recruiter_id=current_user.id,
        title=body.title,
        description=body.description,
        required_skills=body.required_skills,
        is_active=body.is_active,
    )
    session.add(job)
    await session.flush()  # job.id is assigned here; needed for the embedding job's payload
    await session.commit()

    try:
        async_job = await enqueue_job(
            session,
            redis,
            job_type=JOB_TYPE_POSTING_EMBED,
            user_id=current_user.id,
            payload={"job_id": str(job.id)},
        )
    except EnqueueFailedError as exc:
        # The posting itself is still valid (title/description/required_skills are all set); only the
        # embedding step failed to enqueue, so the row survives with embedding left NULL rather than
        # being deleted - a recruiter can still see it, and matching backends already treat NULL as
        # "not embedded yet" without erroring.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="posting was created but could not enqueue embedding",
        ) from exc

    return PostingCreateOut(posting=PostingOut.from_job(job), async_job_id=async_job.id)


@router.get("", response_model=list[PostingOut])
async def list_postings(
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_recruiter),
) -> list[PostingOut]:
    """List the caller's own postings, newest first. Recruiters never see other recruiters' postings."""
    result = await session.execute(
        select(Job).where(Job.recruiter_id == current_user.id).order_by(Job.created_at.desc())
    )
    return [PostingOut.from_job(job) for job in result.scalars().all()]


async def _get_owned_posting(session: AsyncSession, posting_id: uuid.UUID, recruiter_id: uuid.UUID) -> Job:
    """Shared lookup for GET/PATCH `/postings/{id}`: 404 (not 403) for missing or not-owned ids."""
    job = await session.get(Job, posting_id)
    if job is None or job.recruiter_id != recruiter_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="posting not found")
    return job


@router.get("/{posting_id}", response_model=PostingOut)
async def read_posting(
    posting_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_recruiter),
) -> PostingOut:
    """Return one posting if it belongs to the caller; otherwise 404 (ids not enumerable)."""
    job = await _get_owned_posting(session, posting_id, current_user.id)
    return PostingOut.from_job(job)


@router.patch("/{posting_id}", response_model=PostingOut)
async def update_posting(
    posting_id: uuid.UUID,
    body: PostingUpdate,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_recruiter),
) -> PostingOut:
    """Flip `is_active` on the caller's own posting. No hard delete exists for postings."""
    job = await _get_owned_posting(session, posting_id, current_user.id)
    job.is_active = body.is_active
    await session.commit()
    await session.refresh(job)
    return PostingOut.from_job(job)
