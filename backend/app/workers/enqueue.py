"""Insert an `async_jobs` row as queued, commit, then push the matching ARQ function onto Redis."""

import uuid  # user_id and the returned job id are UUIDs

from arq.connections import ArqRedis  # type of the FastAPI app.state.redis pool
from sqlalchemy.ext.asyncio import AsyncSession  # request-scoped session from get_db_session

from app.models.async_job import AsyncJob  # row the frontend polls via GET /jobs/{id}
from app.models.enums import AsyncJobStatus  # always start at QUEUED
from app.workers.job_types import JOB_TYPE_TO_FUNCTION  # maps job_type -> ARQ function name


class UnknownJobTypeError(ValueError):
    """Raised when enqueue is asked to run a job_type with no registered ARQ function."""


class EnqueueFailedError(RuntimeError):
    """Raised when the Postgres row was written but Redis enqueue failed or returned a duplicate."""


async def enqueue_job(
    session: AsyncSession,
    redis: ArqRedis,
    *,
    job_type: str,
    user_id: uuid.UUID | None,
    payload: dict | None = None,
) -> AsyncJob:
    """Persist queued, then enqueue ARQ with `_job_id` equal to the row UUID so the worker can find it.

    Commit happens *before* Redis enqueue. If we enqueued first, a fast worker could look up a row
    that is not committed yet. If Redis then fails, the row is marked failed so it cannot sit in
    queued forever.
    """
    function_name = JOB_TYPE_TO_FUNCTION.get(job_type)  # None means this phase does not know the type
    if function_name is None:
        raise UnknownJobTypeError(f"unknown job_type: {job_type}")  # do not insert a row we cannot run
    job = AsyncJob(
        job_type=job_type,  # stored for GET /jobs/{id} and later result-shape branching
        status=AsyncJobStatus.QUEUED,  # worker has not picked this up yet
        user_id=user_id,  # GET /jobs/{id} allows only this user to poll
        payload=payload,  # JSON input the task handler reads
    )
    session.add(job)  # UUID primary key is assigned in Python before INSERT (mixin default)
    await session.flush()  # persist so job.id is definitely available for _job_id
    await session.commit()  # worker GET must be able to see this row as soon as Redis has the message
    try:
        queued = await redis.enqueue_job(function_name, _job_id=str(job.id))  # no extra args; ctx carries job_id
    except Exception as exc:
        job.status = AsyncJobStatus.FAILED  # do not leave a queued row that will never run
        job.error = f"enqueue failed: {type(exc).__name__}: {exc}"  # short reason for the poller
        await session.commit()  # persist the failed row before raising to the HTTP layer
        raise EnqueueFailedError(str(exc)) from exc  # router turns this into HTTP 503
    if queued is None:
        job.status = AsyncJobStatus.FAILED  # ARQ returns None when _job_id already exists
        job.error = "enqueue failed: duplicate ARQ job id"  # UUID collision is vanishingly rare
        await session.commit()  # persist failed
        raise EnqueueFailedError(job.error)  # router turns this into HTTP 503
    return job  # id is what the frontend polls
