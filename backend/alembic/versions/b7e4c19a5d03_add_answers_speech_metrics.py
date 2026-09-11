"""add answers.speech_metrics json column

Phase 11 (speech-pipeline) persists faster-whisper word timings plus transcript-derived and
acoustic-derived fluency on each answered row that has audio. `answers.transcript` stays plain
text (the utterance string). Structured timings/metrics do not fit a Text column without
breaking the later transcript viewer, so this revision adds a nullable JSON column. No new
Postgres ENUM types: `transcribe` is a plain-string ARQ job type.

Revision ID: b7e4c19a5d03
Revises: c4e91f7a2d08
Create Date: 2026-09-01 12:00:00.000000

"""

from collections.abc import Sequence  # typing helper for the branch_labels/depends_on annotations below

import sqlalchemy as sa  # sa.Column / sa.JSON used by add_column below

from alembic import op  # alembic's migration operations API: add_column, drop_column

# revision identifiers, used by Alembic to order/link migrations into a chain.
revision: str = "b7e4c19a5d03"  # this migration's unique id
down_revision: str | None = "c4e91f7a2d08"  # chains after Phase 9 interview session/answer columns
branch_labels: str | Sequence[str] | None = None  # no branching needed for a single linear history
depends_on: str | Sequence[str] | None = None  # no cross-branch dependency needed here


def upgrade() -> None:
    """Add nullable JSON speech_metrics on answers. No new ENUM types."""
    op.add_column("answers", sa.Column("speech_metrics", sa.JSON(), nullable=True))  # timings + dual fluency


def downgrade() -> None:
    """Reverse upgrade(). No ENUM types were created, so there is nothing to DROP TYPE."""
    op.drop_column("answers", "speech_metrics")  # transcript Text column is unchanged
