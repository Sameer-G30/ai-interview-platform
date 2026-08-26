"""add interview session resume_id and answer evaluation columns

Phase 9 (interview-engine) persists generated questions as `answers` rows and stores the Phase 8
`AnswerEvaluation` JSON on each answered row. `interview_sessions` did not have `resume_id` (every
session is generated from one parsed resume, same 404/409 selection as GET /matches). `answers`
did not have `evaluation`, `question_kind`, or `is_follow_up`. No new Postgres ENUM types: job
types stay plain strings, and question_kind is a varchar so downgrade has no DROP TYPE.

Revision ID: c4e91f7a2d08
Revises: de258b209b24
Create Date: 2026-08-26 14:45:00.000000

"""

from collections.abc import Sequence  # typing helper for the branch_labels/depends_on annotations below

import sqlalchemy as sa  # sa.Column / sa.Uuid / sa.JSON used by add_column below

from alembic import op  # alembic's migration operations API: add_column, create_index, drop_constraint, etc.

# revision identifiers, used by Alembic to order/link migrations into a chain.
revision: str = "c4e91f7a2d08"  # this migration's unique id
down_revision: str | None = "de258b209b24"  # chains after jobs/resumes embedding columns
branch_labels: str | Sequence[str] | None = None  # no branching needed for a single linear history
depends_on: str | Sequence[str] | None = None  # no cross-branch dependency needed here


def upgrade() -> None:
    """Add resume_id on sessions and evaluation/kind/follow-up on answers. No new ENUM types."""
    op.add_column("interview_sessions", sa.Column("resume_id", sa.Uuid(), nullable=False))  # required parsed resume
    op.create_index(op.f("ix_interview_sessions_resume_id"), "interview_sessions", ["resume_id"], unique=False)
    op.create_foreign_key(
        "fk_interview_sessions_resume_id_resumes",  # named so downgrade can drop it explicitly
        "interview_sessions",
        "resumes",
        ["resume_id"],
        ["id"],
        ondelete="RESTRICT",  # do not delete a resume out from under an in-flight session
    )
    op.add_column(
        "answers",
        sa.Column("question_kind", sa.String(length=32), nullable=False, server_default="technical"),
    )
    op.add_column(
        "answers",
        sa.Column("is_follow_up", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("answers", sa.Column("evaluation", sa.JSON(), nullable=True))  # AnswerEvaluation dict or NULL
    op.create_unique_constraint("uq_answers_session_question_order", "answers", ["session_id", "question_order"])


def downgrade() -> None:
    """Reverse upgrade(). No ENUM types were created, so there is nothing to DROP TYPE."""
    op.drop_constraint("uq_answers_session_question_order", "answers", type_="unique")
    op.drop_column("answers", "evaluation")
    op.drop_column("answers", "is_follow_up")
    op.drop_column("answers", "question_kind")
    op.drop_constraint("fk_interview_sessions_resume_id_resumes", "interview_sessions", type_="foreignkey")
    op.drop_index(op.f("ix_interview_sessions_resume_id"), table_name="interview_sessions")
    op.drop_column("interview_sessions", "resume_id")
