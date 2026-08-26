"""String job_type values stored on `async_jobs.job_type` and mapped to ARQ function names.

These are plain strings (not a Postgres ENUM) so later phases can add transcribe / score
without a migration. Demo, resume_parse, posting_embed, and interview generate/evaluate are registered.
"""

JOB_TYPE_DEMO_ECHO = "demo_echo"  # echoes payload["message"] after an optional sleep; used by the SPA demo
JOB_TYPE_DEMO_FAIL = "demo_fail"  # always raises; used by tests to cover the failed status path
# Resume-pipeline phase: PyMuPDF/pypdfium2 extraction, spaCy sectioning, ESCO skill match, ATS score.
# Still a plain string (not a Postgres ENUM) so later job types (transcribe, evaluate, ...) never need a migration.
JOB_TYPE_RESUME_PARSE = "resume_parse"
# Job-matching phase: embeds one posting's title+description+required_skills text into `jobs.embedding`.
# `POST /postings` enqueues this right after inserting the row, mirroring resume_parse's pattern.
JOB_TYPE_POSTING_EMBED = "posting_embed"
# Interview-engine phase: generate questions for a session, then evaluate one submitted text answer.
# Follow-up questions are produced in the same `interview_evaluate` pass (not a third ARQ type),
# matching resume_parse writing the embedding in the same worker pass. Still plain strings.
JOB_TYPE_INTERVIEW_GENERATE = "interview_generate"
JOB_TYPE_INTERVIEW_EVALUATE = "interview_evaluate"

# ARQ enqueue_job's first argument is the worker function's registered name, which we keep identical
# to job_type so the Postgres row and the Redis message point at the same handler.
JOB_TYPE_TO_FUNCTION: dict[str, str] = {
    JOB_TYPE_DEMO_ECHO: "demo_echo",  # handled by app.workers.tasks.demo_echo
    JOB_TYPE_DEMO_FAIL: "demo_fail",  # handled by app.workers.tasks.demo_fail
    JOB_TYPE_RESUME_PARSE: "resume_parse",  # handled by app.workers.tasks.resume_parse
    JOB_TYPE_POSTING_EMBED: "posting_embed",  # handled by app.workers.tasks.posting_embed
    JOB_TYPE_INTERVIEW_GENERATE: "interview_generate",  # handled by app.workers.tasks.interview_generate
    JOB_TYPE_INTERVIEW_EVALUATE: "interview_evaluate",  # handled by app.workers.tasks.interview_evaluate
}
