"""add core domain tables: users, jobs, resumes, interview_sessions, answers, scores, async_jobs

Hand-edited after autogenerate to add: this docstring's per-line explanation, and explicit
`DROP TYPE` statements in `downgrade()` for the four native Postgres ENUMs this revision creates
(`user_role`, `resume_status`, `interview_session_status`, `async_job_status`) - Alembic's
autogenerate drops the tables that use an enum but never the enum type itself, which would break
a downgrade -> upgrade round trip with a "type already exists" error on the second upgrade.

Revision ID: 0a764d64c629
Revises: 31f80c6d12f3
Create Date: 2026-08-23 13:50:46.886585

"""

from collections.abc import Sequence  # typing helper for the branch_labels/depends_on annotations below

import sqlalchemy as sa  # column/type declarations (String, Enum, Uuid, JSON, ...) used by every op.create_table call

from alembic import op  # alembic's migration operations API: create_table, create_index, execute, etc.

# revision identifiers, used by Alembic to order/link migrations into a chain.
revision: str = "0a764d64c629"                 # this migration's unique id
down_revision: str | None = "31f80c6d12f3"      # chains directly after the pgvector-extension baseline
branch_labels: str | Sequence[str] | None = None  # no branching needed for a single linear history
depends_on: str | Sequence[str] | None = None     # no cross-branch dependency needed here


def upgrade() -> None:
    """Create all seven Phase 2 tables, their indexes, FKs, and the four native enum types they use."""
    # --- users: the single account table for both candidates and recruiters (admin is a flag). ---
    op.create_table(
        "users",
        sa.Column("email", sa.String(length=320), nullable=False),  # login identifier, unique below
        sa.Column("hashed_password", sa.String(length=255), nullable=False),  # Argon2id hash, never plaintext
        sa.Column("full_name", sa.String(length=200), nullable=True),  # optional display name
        # native_enum creates a real Postgres ENUM type named "user_role" rather than a plain varchar.
        sa.Column("role", sa.Enum("CANDIDATE", "RECRUITER", name="user_role"), nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False),  # only meaningful when role == RECRUITER
        sa.Column("is_active", sa.Boolean(), nullable=False),  # soft-disable switch for locked accounts
        sa.Column("id", sa.Uuid(), nullable=False),  # client-generated UUID4 primary key
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),  # row creation timestamp
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),  # last-modified timestamp
        sa.PrimaryKeyConstraint("id"),
    )
    # Unique index doubles as the fast lookup path login/register use to find a user by email.
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)

    # --- async_jobs: generic queue status table, referenced by user_id but no other table depends on it. ---
    op.create_table(
        "async_jobs",
        sa.Column("job_type", sa.String(length=50), nullable=False),  # discriminator, e.g. "resume_parse"
        sa.Column(
            "status", sa.Enum("QUEUED", "RUNNING", "SUCCEEDED", "FAILED", name="async_job_status"), nullable=False
        ),
        sa.Column("user_id", sa.Uuid(), nullable=True),  # who triggered the job, if applicable
        sa.Column("payload", sa.JSON(), nullable=True),  # worker input, shape depends on job_type
        sa.Column("result", sa.JSON(), nullable=True),  # worker output once status == SUCCEEDED
        sa.Column("error", sa.Text(), nullable=True),  # human-readable failure reason if status == FAILED
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        # SET NULL: deleting a user keeps the job's audit trail instead of cascading it away.
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_async_jobs_job_type"), "async_jobs", ["job_type"], unique=False)
    op.create_index(op.f("ix_async_jobs_user_id"), "async_jobs", ["user_id"], unique=False)

    # --- jobs: postings created by recruiters; candidates match/interview against these later. ---
    op.create_table(
        "jobs",
        sa.Column("recruiter_id", sa.Uuid(), nullable=False),  # owning recruiter, role-checked at the API layer
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("required_skills", sa.Text(), nullable=True),  # freeform for now; formalized in job-matching phase
        sa.Column("is_active", sa.Boolean(), nullable=False),  # lets a recruiter close a posting without deleting it
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        # CASCADE: deleting a recruiter account also removes the postings only they could manage.
        sa.ForeignKeyConstraint(["recruiter_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_jobs_recruiter_id"), "jobs", ["recruiter_id"], unique=False)

    # --- refresh_tokens: backs rotate-on-use refresh tokens with reuse detection (see app/auth/service.py). ---
    op.create_table(
        "refresh_tokens",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),  # sha256 hex of the raw token, unique
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),  # defined directly, not via a mixin
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),  # hard expiry, checked on every refresh
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),  # NULL = still valid
        sa.Column("replaced_by_id", sa.Uuid(), nullable=True),  # self-referential rotation-chain pointer
        sa.Column("id", sa.Uuid(), nullable=False),
        # Self-referential FK: SET NULL so deleting a newer token doesn't cascade-delete its predecessor.
        sa.ForeignKeyConstraint(["replaced_by_id"], ["refresh_tokens.id"], ondelete="SET NULL"),
        # CASCADE: deleting a user's account invalidates every refresh token they ever held.
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    # Unique: token_hash is how a raw refresh token is looked up; two tokens colliding would be a bug/attack.
    op.create_index(op.f("ix_refresh_tokens_token_hash"), "refresh_tokens", ["token_hash"], unique=True)
    op.create_index(op.f("ix_refresh_tokens_user_id"), "refresh_tokens", ["user_id"], unique=False)

    # --- resumes: uploaded files; parsed_data/ats_score stay NULL until the resume-pipeline phase. ---
    op.create_table(
        "resumes",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("file_path", sa.String(length=500), nullable=False),  # path under Settings.storage_root
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column(
            "status", sa.Enum("UPLOADED", "PROCESSING", "PARSED", "FAILED", name="resume_status"), nullable=False
        ),
        sa.Column("parsed_data", sa.JSON(), nullable=True),  # sections/skills, filled in by the parse worker later
        sa.Column("ats_score", sa.Float(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        # CASCADE: a deleted candidate's resumes have no remaining owner and no reason to keep them.
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_resumes_user_id"), "resumes", ["user_id"], unique=False)

    # --- interview_sessions: one candidate's attempt, optionally targeted at a specific job. ---
    op.create_table(
        "interview_sessions",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),  # nullable: generic practice sessions don't target a job
        sa.Column(
            "status",
            sa.Enum("SCHEDULED", "IN_PROGRESS", "COMPLETED", "ABANDONED", name="interview_session_status"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),  # set when the first answer is given
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),  # set when status -> COMPLETED
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        # SET NULL: deleting a job posting shouldn't erase candidates' interview history against it.
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
        # CASCADE: deleting a candidate account removes their session history along with it.
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_interview_sessions_job_id"), "interview_sessions", ["job_id"], unique=False)
    op.create_index(op.f("ix_interview_sessions_user_id"), "interview_sessions", ["user_id"], unique=False)

    # --- answers: one question/response pair within a session; transcript/audio filled in later phases. ---
    op.create_table(
        "answers",
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("question_order", sa.Integer(), nullable=False),  # 0-based position within the session
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("answer_text", sa.Text(), nullable=True),  # populated for typed answers
        sa.Column("audio_path", sa.String(length=500), nullable=True),  # populated once MediaRecorder upload lands
        sa.Column("transcript", sa.Text(), nullable=True),  # populated by the speech-pipeline phase's ASR worker
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        # CASCADE: deleting a session removes every answer that belongs only to it.
        sa.ForeignKeyConstraint(["session_id"], ["interview_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_answers_session_id"), "answers", ["session_id"], unique=False)

    # --- scores: one composite score row per session, with a JSON attribution breakdown per Part 4 of the plan. ---
    op.create_table(
        "scores",
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("resume_score", sa.Float(), nullable=True),
        sa.Column("technical_score", sa.Float(), nullable=True),
        sa.Column("communication_score", sa.Float(), nullable=True),
        sa.Column("behavioral_score", sa.Float(), nullable=True),
        sa.Column("composite_score", sa.Float(), nullable=True),
        sa.Column("attribution", sa.JSON(), nullable=True),  # per-signal weight/value/contribution breakdown
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        # CASCADE: a score with no session behind it is meaningless.
        sa.ForeignKeyConstraint(["session_id"], ["interview_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        # unique: enforces exactly one composite score row per session, matching the plan's aggregation step.
        sa.UniqueConstraint("session_id"),
    )


def downgrade() -> None:
    """Drop every table this revision created, then the four native enum types they depended on.

    Table drop order is the reverse of creation (children before the parents they FK to); the enum
    `DROP TYPE` statements come last and are the hand-added part - autogenerate's downgrade template
    never emits these, but leaving them out would break a downgrade -> upgrade round trip.
    """
    op.drop_table("scores")
    op.drop_index(op.f("ix_answers_session_id"), table_name="answers")
    op.drop_table("answers")
    op.drop_index(op.f("ix_interview_sessions_user_id"), table_name="interview_sessions")
    op.drop_index(op.f("ix_interview_sessions_job_id"), table_name="interview_sessions")
    op.drop_table("interview_sessions")
    op.drop_index(op.f("ix_resumes_user_id"), table_name="resumes")
    op.drop_table("resumes")
    op.drop_index(op.f("ix_refresh_tokens_user_id"), table_name="refresh_tokens")
    op.drop_index(op.f("ix_refresh_tokens_token_hash"), table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
    op.drop_index(op.f("ix_jobs_recruiter_id"), table_name="jobs")
    op.drop_table("jobs")
    op.drop_index(op.f("ix_async_jobs_user_id"), table_name="async_jobs")
    op.drop_index(op.f("ix_async_jobs_job_type"), table_name="async_jobs")
    op.drop_table("async_jobs")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")

    # Postgres ENUM types are independent objects, not dropped automatically when the columns/tables
    # using them are dropped - each must be dropped explicitly or a later upgrade() would fail trying
    # to CREATE a type that already exists.
    sa.Enum(name="interview_session_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="resume_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="async_job_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="user_role").drop(op.get_bind(), checkfirst=True)
