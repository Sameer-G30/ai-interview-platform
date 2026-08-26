"""ARQ WorkerSettings class consumed by `uv run arq app.workers.settings.WorkerSettings`."""

from arq.worker import Worker, func  # Worker for in-process burst tests; func() sets per-task max_tries

from app.core.redis import get_redis_settings  # same REDIS_URL the API uses
from app.workers.tasks import (  # demo + resume/posting ML + interview generate/evaluate
    demo_echo,
    demo_fail,
    interview_evaluate,
    interview_generate,
    posting_embed,
    resume_parse,
)


async def startup(ctx: dict) -> None:
    """Hook for later phases (HTTP clients, lazy-loaded models). Phase 4 has nothing to warm up."""
    ctx["started"] = True  # ARQ requires startup to be a coroutine; a flag keeps it non-empty


async def shutdown(ctx: dict) -> None:
    """Hook for later phases to unload models. Phase 4 does not dispose the shared SQLAlchemy engine.

    Tests run a burst Worker in the same process as FastAPI; disposing the shared engine in this
    hook would break the subsequent GET /jobs/{id} in that test.
    """
    ctx.pop("started", None)  # drop the startup flag; nothing else to close in this phase


class WorkerSettings:
    """Class-level ARQ config. The CLI copies attributes that match Worker.__init__ parameter names."""

    functions = [
        func(demo_echo, name="demo_echo", max_tries=1),  # one try: failed demo jobs must not retry in tests
        func(demo_fail, name="demo_fail", max_tries=1),  # same: FAILED is terminal for the demo path
        # 60s cap: PyMuPDF/spaCy/PhraseMatcher on a resume-sized PDF is sub-second in practice, but a
        # pathological file (huge page count, degenerate text layer) must not hang the worker forever.
        # The SBERT embedding step added in the job-matching phase runs in this same task/timeout.
        func(resume_parse, name="resume_parse", max_tries=1, timeout=60),
        # Embedding one posting's title+description+required_skills text is a single small SBERT
        # encode call; 60s matches resume_parse's cap even though it typically finishes in well under 1s.
        func(posting_embed, name="posting_embed", max_tries=1, timeout=60),
        # LLM generate/evaluate: httpx read timeout is 120s; evaluate may do a second complete_json for
        # a follow-up in the same pass. 300s cap is the 8GB-card cold-load budget, not a keep_alive tweak.
        func(interview_generate, name="interview_generate", max_tries=1, timeout=180),
        func(interview_evaluate, name="interview_evaluate", max_tries=1, timeout=300),
    ]
    redis_settings = get_redis_settings()  # parsed once at import from REDIS_URL / Settings
    on_startup = startup  # called when the worker process (or burst Worker) starts
    on_shutdown = shutdown  # called when the worker process (or burst Worker) stops
    max_tries = 1  # default for any function that forgets func(..., max_tries=1)
    retry_jobs = False  # do not re-queue crashed jobs; the Postgres row already records failed
    job_timeout = 60  # seconds; demo jobs are sub-second, resume/whisper later will raise this


async def run_burst_worker() -> None:
    """Drain the default ARQ queue once and exit. Used by tests, not by the long-running worker."""
    worker = Worker(
        functions=WorkerSettings.functions,  # same demo_echo / demo_fail registration as the CLI worker
        redis_settings=WorkerSettings.redis_settings,  # own Redis pool, closed in worker.close()
        on_startup=WorkerSettings.on_startup,  # keep startup behavior identical to production
        on_shutdown=WorkerSettings.on_shutdown,  # keep shutdown behavior identical to production
        burst=True,  # process everything currently queued, wait one empty poll, then stop
        poll_delay=0.01,  # tests should not wait the production 0.5s idle poll
        handle_signals=False,  # do not install SIGINT handlers that would interfere with pytest
        max_tries=1,  # belt-and-suspenders with func(max_tries=1)
        retry_jobs=False,  # failed jobs stay failed
    )
    try:
        await worker.async_run()  # blocks until the burst queue is empty
    finally:
        await worker.close()  # close the worker's Redis pool even if async_run raises
