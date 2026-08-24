"""`/jobs/*` endpoints: enqueue a demo job and poll status. Only the owning user may GET a job."""

import uuid  # path param for GET /jobs/{job_id}

from arq.connections import ArqRedis  # injected Redis pool from app.state
from fastapi import APIRouter, Depends, HTTPException, Request, status  # routing / DI / errors
from sqlalchemy.ext.asyncio import AsyncSession  # request-scoped DB session

from app.auth.dependencies import get_current_user  # bearer access JWT -> User
from app.core.db import get_db_session  # yields the request-scoped AsyncSession
from app.core.rate_limit import limiter  # slowapi limiter; POST demo is tighter than the default
from app.models.async_job import AsyncJob  # row loaded by GET
from app.models.user import User  # type of the authenticated caller
from app.schemas.jobs import AsyncJobOut, DemoJobRequest  # request/response contracts
from app.workers.enqueue import EnqueueFailedError, enqueue_job  # insert queued + Redis enqueue
from app.workers.job_types import JOB_TYPE_DEMO_ECHO, JOB_TYPE_DEMO_FAIL  # throwaway Phase 4 types

router = APIRouter(prefix="/jobs", tags=["jobs"])  # every route here lives under /jobs/...


async def get_arq_redis(request: Request) -> ArqRedis:
    """Return the process Redis pool, or 503 if the API started without a queue connection."""
    redis = getattr(request.app.state, "redis", None)  # set in lifespan (uvicorn) or the test fixture
    if redis is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="job queue is not connected",
        )
    return redis  # ArqRedis used by enqueue_job


@router.post("/demo", response_model=AsyncJobOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("20/minute")  # demo enqueue is not a login surface but still should not be spammable
async def create_demo_job(
    request: Request,  # required so slowapi can key the limit on client IP
    body: DemoJobRequest,
    session: AsyncSession = Depends(get_db_session),
    redis: ArqRedis = Depends(get_arq_redis),
    current_user: User = Depends(get_current_user),
) -> AsyncJob:
    """Enqueue a throwaway echo (or fail) job for the caller and return the queued row immediately."""
    job_type = JOB_TYPE_DEMO_FAIL if body.fail else JOB_TYPE_DEMO_ECHO  # tests cover both via this one route
    payload = {"message": body.message, "sleep_ms": body.sleep_ms}  # worker reads these keys
    if body.fail:
        payload["reason"] = body.message  # demo_fail uses reason; reuse message so tests stay one-field
    try:
        job = await enqueue_job(
            session,
            redis,
            job_type=job_type,
            user_id=current_user.id,  # ownership for GET /jobs/{id}
            payload=payload,
        )
    except EnqueueFailedError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="could not enqueue job",
        ) from exc
    return job  # AsyncJobOut via from_attributes; status is queued until a worker picks it up


@router.get("/{job_id}", response_model=AsyncJobOut)
async def read_job(
    job_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> AsyncJob:
    """Return one job if it belongs to the caller; otherwise 404 so ids are not enumerable."""
    job = await session.get(AsyncJob, job_id)  # None if the UUID was never inserted
    if job is None or job.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
    return job  # includes status / result / error for the TanStack Query poller
