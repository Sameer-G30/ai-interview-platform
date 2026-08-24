"""ARQ task functions registered on WorkerSettings.

Phase 4 shipped demo jobs only. The resume-pipeline phase adds `resume_parse`, the first task that
actually calls into `ml/`.
"""

import asyncio  # optional sleep for the demo jobs; asyncio.to_thread runs the sync ml/resume pipeline
import logging  # worker-side log line when a resume fails to parse (short reason only, no traceback here)
import uuid  # resume_id in the job payload is a UUID string on the wire

from ml.resume import ResumeParseError, run_resume_pipeline  # PyMuPDF/pypdfium2 + spaCy + ESCO + ATS, one call

from app.core.db import AsyncSessionLocal  # worker opens its own sessions; it is not a request
from app.models.enums import ResumeStatus  # uploaded / processing / parsed / failed
from app.models.resume import Resume  # row this task advances through its lifecycle
from app.workers.tracked import run_tracked_job  # shared running/succeeded/failed status wrapper

logger = logging.getLogger(__name__)  # module logger, mirrors app.workers.tracked's convention


async def demo_echo(ctx: dict) -> dict:
    """Throwaway success path: echo payload["message"] after payload["sleep_ms"] (capped)."""

    async def _handle(payload: dict | None) -> dict:
        body = payload or {}  # enqueue always stores a dict, but the column is nullable
        sleep_ms = int(body.get("sleep_ms") or 0)  # tests pass 0; the SPA demo may pass a short delay
        if sleep_ms > 0:
            await asyncio.sleep(min(sleep_ms, 5000) / 1000)  # cap at 5s so a bad payload cannot stall the worker
        message = body.get("message", "ok")  # default keeps the job useful even with an empty body
        return {"echo": message}  # JSON-safe result written to async_jobs.result

    return await run_tracked_job(ctx, _handle)  # ctx["job_id"] is the Postgres UUID string


async def demo_fail(ctx: dict) -> dict:
    """Throwaway failure path: always raises so tests can assert status=failed and error is set."""

    async def _handle(payload: dict | None) -> dict:
        body = payload or {}  # optional reason from the test enqueue payload
        reason = str(body.get("reason") or "demo job failed on purpose")  # stable default for assertions
        raise RuntimeError(reason)  # run_tracked_job catches this, writes FAILED, then re-raises

    return await run_tracked_job(ctx, _handle)  # never returns; ARQ sees the exception after Postgres is updated


async def _set_resume_status(resume_id: uuid.UUID, status: ResumeStatus, **extra: object) -> None:
    """Load one `resumes` row in its own session and update status (+ optional extra columns)."""
    async with AsyncSessionLocal() as session:
        resume = await session.get(Resume, resume_id)
        if resume is None:
            raise RuntimeError(f"resume {resume_id} was not found")  # POST /resumes must commit before enqueue
        resume.status = status
        for column, value in extra.items():
            setattr(resume, column, value)
        await session.commit()


async def resume_parse(ctx: dict) -> dict:
    """Extract text, section it, match ESCO skills, and ATS-score one uploaded resume PDF.

    Mirrors `run_tracked_job`'s async_jobs bookkeeping but *also* advances the linked `resumes` row
    (uploaded -> processing -> parsed/failed) since the candidate-facing results endpoint reads
    `resumes`, not `async_jobs`, directly. `ml/resume` is entirely synchronous (PyMuPDF, spaCy);
    `asyncio.to_thread` keeps it from blocking the worker's event loop for other concurrent jobs.
    """

    async def _handle(payload: dict | None) -> dict:
        body = payload or {}
        resume_id = uuid.UUID(str(body["resume_id"]))  # enqueue helper always sets this key
        async with AsyncSessionLocal() as session:  # separate short session just to read file_path
            resume = await session.get(Resume, resume_id)
            if resume is None:
                raise RuntimeError(f"resume {resume_id} was not found")
            file_path = resume.file_path
        await _set_resume_status(resume_id, ResumeStatus.PROCESSING)  # visible to GET /resumes/{id} immediately
        try:
            parsed_data, ats_score = await asyncio.to_thread(run_resume_pipeline, file_path)
        except ResumeParseError as exc:
            logger.warning("resume %s failed to parse: %s", resume_id, exc)  # expected failure mode, not a bug
            await _set_resume_status(resume_id, ResumeStatus.FAILED)
            raise
        except Exception:
            logger.exception("resume %s parse worker crashed unexpectedly", resume_id)  # unexpected: full traceback
            await _set_resume_status(resume_id, ResumeStatus.FAILED)
            raise
        await _set_resume_status(resume_id, ResumeStatus.PARSED, parsed_data=parsed_data, ats_score=ats_score)
        return {"resume_id": str(resume_id), "ats_score": ats_score, "skill_count": len(parsed_data["skills"])}

    return await run_tracked_job(ctx, _handle)  # async_jobs row mirrors the same succeeded/failed outcome
