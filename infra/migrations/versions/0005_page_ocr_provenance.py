"""Page-image references and OCR block provenance.

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-17 05:04:16.750252
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("pages", sa.Column("image_storage_key", sa.String(length=1024), nullable=True))
    op.add_column("pages", sa.Column("ocr_blocks", postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column("pages", "ocr_blocks")
    op.drop_column("pages", "image_storage_key")
