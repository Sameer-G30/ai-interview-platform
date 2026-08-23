"""Python string enums shared by ORM models and Pydantic schemas.

Using `str, Enum` (not plain Enum) means these serialize as plain strings in JSON responses
and compare equal to raw strings, while SQLAlchemy still maps them to native Postgres ENUM
types via `sqlalchemy.Enum`.
"""

from enum import Enum  # base class for all string-backed enums below


class UserRole(str, Enum):
    """Only two role trees exist per Part 0 of the plan; admin is a flag, not a third role."""

    CANDIDATE = "candidate"  # practices interviews, uploads resumes, views own scores/dashboard
    RECRUITER = "recruiter"  # posts jobs, views candidate rankings/reports; admin flag layers on top of this


class ResumeStatus(str, Enum):
    """Lifecycle of an uploaded resume through the (not-yet-built) parsing pipeline."""

    UPLOADED = "uploaded"      # file stored, not yet queued for parsing
    PROCESSING = "processing"  # picked up by the parse worker (queue-infrastructure phase)
    PARSED = "parsed"          # parsing + ATS scoring completed successfully
    FAILED = "failed"          # parsing raised an error; see linked async_job.error for detail


class InterviewSessionStatus(str, Enum):
    """Lifecycle of one candidate's interview attempt."""

    SCHEDULED = "scheduled"      # session row created, candidate hasn't started answering yet
    IN_PROGRESS = "in_progress"  # candidate is actively answering questions
    COMPLETED = "completed"      # all questions answered, ready for scoring
    ABANDONED = "abandoned"      # candidate left without completing; excluded from ranking


class AsyncJobStatus(str, Enum):
    """Generic status for the `async_jobs` table backing every queued ML task (ARQ, later phase)."""

    QUEUED = "queued"        # enqueued to Redis, worker hasn't picked it up yet
    RUNNING = "running"      # worker is actively processing it
    SUCCEEDED = "succeeded"  # completed; `result` column holds the output payload
    FAILED = "failed"        # worker raised; `error` column holds the message/traceback summary
