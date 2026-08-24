"""ARQ task functions registered on WorkerSettings. Phase 4 ships demo jobs only; no ml/ calls."""

import asyncio  # optional sleep so the SPA demo can show queued -> running -> succeeded

from app.workers.tracked import run_tracked_job  # shared running/succeeded/failed status wrapper


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
