"""Full-text search index on chunk content for lexical retrieval.

Adds a GIN expression index over `to_tsvector('simple', content)`. The
`simple` configuration is deliberate: it applies no language-specific
stemming or stop words, so Tamil, English, and romanized Tanglish tokens are
all indexed on equal footing. A stemming configuration would silently drop
Tamil tokens it does not understand, harming recall for the languages this
platform exists to serve.

The index is expression-based and is created/dropped only here; like the
IVFFlat ANN index it does not round-trip through Alembic autogenerate, so it
is excluded from drift comparison in `infra/migrations/env.py`.

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-23
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX_NAME = "ix_chunks_content_fts"


def upgrade() -> None:
    op.execute(
        f"CREATE INDEX {INDEX_NAME} ON chunks "
        "USING gin (to_tsvector('simple', content))"
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {INDEX_NAME}")
