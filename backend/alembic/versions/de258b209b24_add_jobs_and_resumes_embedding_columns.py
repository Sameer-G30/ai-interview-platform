"""add jobs and resumes embedding columns

Adds the 384-d `vector` columns the job-matching phase needs: `jobs.embedding` (written by the new
`posting_embed` worker task) and `resumes.embedding` (written by `resume_parse` right after
`parsed_data`/`ats_score`). Both are nullable - existing rows, and rows whose embedding job hasn't
run yet, simply have `NULL` until a worker fills them in. Depends on `31f80c6d12f3` (the baseline
migration that enables the `vector` extension) having already run, transitively via `0a764d64c629`.

Revision ID: de258b209b24
Revises: 0a764d64c629
Create Date: 2026-08-24 22:03:53.994175

"""

from collections.abc import Sequence  # typing helper for the branch_labels/depends_on annotations below

import sqlalchemy as sa  # sa.Column wraps the pgvector type below, same pattern as every other revision
from pgvector.sqlalchemy import Vector  # pgvector's SQLAlchemy column type, matches app/models/{job,resume}.py

from alembic import op  # alembic's migration operations API: add_column, drop_column, etc.

# revision identifiers, used by Alembic to order/link migrations into a chain.
revision: str = "de258b209b24"                 # this migration's unique id
down_revision: str | None = "0a764d64c629"      # chains directly after the Phase 2 core-tables migration
branch_labels: str | Sequence[str] | None = None  # no branching needed for a single linear history
depends_on: str | Sequence[str] | None = None     # no cross-branch dependency needed here


def upgrade() -> None:
    """Add the nullable 384-d embedding column to both `jobs` and `resumes`."""
    op.add_column("jobs", sa.Column("embedding", Vector(384), nullable=True))
    op.add_column("resumes", sa.Column("embedding", Vector(384), nullable=True))


def downgrade() -> None:
    """Drop both embedding columns, reversing upgrade(). No enum types are involved this time."""
    op.drop_column("resumes", "embedding")
    op.drop_column("jobs", "embedding")
