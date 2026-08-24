"""String job_type values stored on `async_jobs.job_type` and mapped to ARQ function names.

These are plain strings (not a Postgres ENUM) so later phases can add resume_parse / transcribe /
evaluate without a migration. Phase 4 only ships throwaway demo types so the queue is testable
without calling `ml/`.
"""

JOB_TYPE_DEMO_ECHO = "demo_echo"  # echoes payload["message"] after an optional sleep; used by the SPA demo
JOB_TYPE_DEMO_FAIL = "demo_fail"  # always raises; used by tests to cover the failed status path
# Resume-pipeline phase: PyMuPDF/pypdfium2 extraction, spaCy sectioning, ESCO skill match, ATS score.
# Still a plain string (not a Postgres ENUM) so later job types (transcribe, evaluate, ...) never need a migration.
JOB_TYPE_RESUME_PARSE = "resume_parse"

# ARQ enqueue_job's first argument is the worker function's registered name, which we keep identical
# to job_type so the Postgres row and the Redis message point at the same handler.
JOB_TYPE_TO_FUNCTION: dict[str, str] = {
    JOB_TYPE_DEMO_ECHO: "demo_echo",  # handled by app.workers.tasks.demo_echo
    JOB_TYPE_DEMO_FAIL: "demo_fail",  # handled by app.workers.tasks.demo_fail
    JOB_TYPE_RESUME_PARSE: "resume_parse",  # handled by app.workers.tasks.resume_parse
}
