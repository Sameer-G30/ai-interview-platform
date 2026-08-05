"""enable pgvector extension

This is the baseline migration: it guarantees the `vector` extension exists even if a
future environment (e.g. a managed cloud Postgres) isn't provisioned via our
docker-compose init script. Every later migration that adds `vector` columns depends on
this one having run first.

Revision ID: 31f80c6d12f3
Revises:
Create Date: 2026-08-05 16:33:31.640768

"""

from collections.abc import Sequence  # typing helper for the branch_labels/depends_on annotations below

from alembic import op  # alembic's migration operations API (op.execute, op.create_table, etc.)

# revision identifiers, used by Alembic to order/link migrations into a chain.
revision: str = "31f80c6d12f3"          # this migration's unique id
down_revision: str | None = None        # None marks this as the first migration in the chain
branch_labels: str | Sequence[str] | None = None  # no branching needed for a single linear history
depends_on: str | Sequence[str] | None = None     # no cross-branch dependency needed here


def upgrade() -> None:
    """Enable the pgvector extension so later migrations can declare `vector` columns."""
    # IF NOT EXISTS makes this safe to re-run / safe even if the compose init script already enabled it.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    """Drop the pgvector extension, reversing upgrade()."""
    # Only safe once no tables still reference the `vector` type; fine at this baseline point.
    op.execute("DROP EXTENSION IF EXISTS vector")
