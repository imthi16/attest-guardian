"""Durable purge records so permanent deletion survives a storage failure.

Row deletion and object deletion cannot share a transaction. Committing this
record with the deletion turns the cross-system step into a retryable one: the
sweeper deletes the objects afterwards and marks the record complete, so a
failure delays the purge instead of stranding a document whose bytes are gone.

Tenant isolation matches the other tenant tables (migration `0003`); the
sweeper reads across workspaces and therefore needs the same BYPASSRLS role the
ingestion worker already requires.

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PREDICATE = "workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid"


def upgrade() -> None:
    op.create_table(
        "storage_purges",
        # No foreign key to documents: the document row is already gone by the
        # time this record is acted on.
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("key_prefix", sa.Text(), nullable=False),
        sa.Column(
            "keys",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_storage_purges_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_storage_purges")),
    )
    op.create_index(
        op.f("ix_storage_purges_document_id"),
        "storage_purges",
        ["document_id"],
    )
    op.create_index(
        op.f("ix_storage_purges_workspace_id"),
        "storage_purges",
        ["workspace_id"],
    )
    op.execute("ALTER TABLE storage_purges ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE storage_purges FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY storage_purges_tenant_isolation ON storage_purges "
        f"USING ({_PREDICATE}) WITH CHECK ({_PREDICATE})"
    )


def downgrade() -> None:
    op.execute("DROP POLICY storage_purges_tenant_isolation ON storage_purges")
    op.execute("ALTER TABLE storage_purges NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE storage_purges DISABLE ROW LEVEL SECURITY")
    op.drop_index(op.f("ix_storage_purges_workspace_id"), table_name="storage_purges")
    op.drop_index(op.f("ix_storage_purges_document_id"), table_name="storage_purges")
    op.drop_table("storage_purges")
