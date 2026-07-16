"""Granular pipeline stage on ingestion jobs.

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STAGES = (
    "uploaded",
    "validating",
    "scanning",
    "parsing",
    "ocr",
    "normalizing",
    "chunking",
    "embedding",
    "indexing",
    "ready",
)


def upgrade() -> None:
    stage_enum = postgresql.ENUM(*_STAGES, name="ingestion_stage")
    stage_enum.create(op.get_bind())
    op.add_column(
        "ingestion_jobs",
        sa.Column(
            "stage",
            sa.Enum(*_STAGES, name="ingestion_stage", create_type=False),
            server_default="uploaded",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("ingestion_jobs", "stage")
    postgresql.ENUM(name="ingestion_stage").drop(op.get_bind())
