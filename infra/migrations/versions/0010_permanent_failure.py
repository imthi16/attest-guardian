"""Distinguish permanent ingestion failures from transient ones.

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Existing rows default to False: a failure recorded before this column
    # existed has no stored verdict, and treating it as retryable preserves the
    # behaviour those jobs were created under.
    op.add_column(
        "ingestion_jobs",
        sa.Column(
            "permanent_failure",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("ingestion_jobs", "permanent_failure")
