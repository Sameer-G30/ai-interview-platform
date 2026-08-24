"""Wrap every ARQ task so Postgres `async_jobs` status is updated running / succeeded / failed.

The API never runs ML inline: it writes queued + enqueues to Redis. The worker is the only
process that flips status to running/succeeded/failed. Full tracebacks stay in worker logs;
the `error` column holds a short summary the frontend can show.
"""

import logging  # worker-side exception logs (tracebacks do not go into async_jobs.error)
import uuid  # ARQ ctx["job_id"] is the Postgres async_jobs.id as a string
from collections.abc import Awaitable, Callable  # handler type: payload in, JSON-safe dict out

from app.core.db import AsyncSessionLocal  # worker opens its own sessions; it is not a request
from app.models.async_job import AsyncJob  # the status/result row the frontend polls
from app.models.enums import AsyncJobStatus  # queued / running / succeeded / failed

logger = logging.getLogger(__name__)  # module logger so worker output is greppable by job id

# Max chars stored on async_jobs.error so a pathological exception message cannot bloat the row.
_ERROR_MAX_LEN = 4000

# Handler signature: receives the row's payload (or None) and returns a JSON-serializable result dict.
JobHandler = Callable[[dict | None], Awaitable[dict]]


def _format_error(exc: BaseException) -> str:
    """Short, frontend-safe failure summary; the traceback is logger.exception'd separately."""
    text = f"{type(exc).__name__}: {exc}"  # e.g. "RuntimeError: demo job failed on purpose"
    if len(text) <= _ERROR_MAX_LEN:
        return text  # common case: a one-line message
    return text[: _ERROR_MAX_LEN - 3] + "..."  # truncate rather than storing a novel in Postgres


async def run_tracked_job(ctx: dict, handler: JobHandler) -> dict:
    """Mark the job running, run handler, then persist succeeded/failed. Re-raises on failure.

    Uses separate sessions for running / outcome writes so a handler exception cannot leave the
    session in a failed transaction that would block the FAILED update.
    """
    job_id = uuid.UUID(str(ctx["job_id"]))  # enqueue helper sets ARQ _job_id to the Postgres UUID
    async with AsyncSessionLocal() as session:  # session 1: flip queued -> running
        job = await session.get(AsyncJob, job_id)  # lookup by primary key
        if job is None:
            raise RuntimeError(f"async_jobs row {job_id} was not found")  # enqueue must commit first
        payload = job.payload  # copy before commit; handler must not need a live ORM instance
        job.status = AsyncJobStatus.RUNNING  # frontend polling can now show "running"
        await session.commit()  # visible to GET /jobs/{id} before the handler finishes
    try:
        result = await handler(payload)  # throwaway demo or, later, ml/ work; must return a dict
    except Exception as exc:
        logger.exception("async job %s failed", job_id)  # full traceback in worker logs only
        async with AsyncSessionLocal() as session:  # session 2: record failure even if handler broke
            job = await session.get(AsyncJob, job_id)  # re-load; the running session is already closed
            if job is not None:
                job.status = AsyncJobStatus.FAILED  # terminal state; polling hook stops
                job.error = _format_error(exc)  # short message for GET /jobs/{id}
                await session.commit()  # persist failed before we re-raise for ARQ
        raise  # ARQ records the Redis-side failure; max_tries=1 so it will not retry demo jobs
    async with AsyncSessionLocal() as session:  # session 3: record success
        job = await session.get(AsyncJob, job_id)  # re-load after handler
        if job is None:
            raise RuntimeError(f"async_jobs row {job_id} disappeared")  # should not happen
        job.status = AsyncJobStatus.SUCCEEDED  # terminal state; polling hook stops
        job.result = result  # JSON column; shape depends on job_type
        job.error = None  # clear any stale error if we ever retry a row (demo jobs do not)
        await session.commit()  # GET /jobs/{id} now returns the result payload
    return result  # ARQ also stores this in Redis; Postgres is the source of truth for the API
