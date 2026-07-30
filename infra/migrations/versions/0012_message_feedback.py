"""Reviewer feedback on assistant answers.

One row per message per reviewer, so resubmitting revises a verdict instead of
stacking duplicates. Tenant isolation matches the other tenant tables
(migration `0003`): a denormalized `workspace_id` plus a row-level-security
policy, enforced for non-superuser roles.

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PREDICATE = "workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid"


def upgrade() -> None:
    op.create_table(
        "message_feedback",
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("reviewer_id", sa.Uuid(), nullable=False),
        # `create_table` creates the enum type itself, as in migration 0001;
        # pre-creating it here as well would fail with "type already exists".
        sa.Column(
            "rating",
            sa.Enum("helpful", "unhelpful", "incorrect", name="feedback_rating"),
            nullable=False,
        ),
        sa.Column("note", sa.Text(), nullable=True),
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
            ["message_id"],
            ["messages.id"],
            name=op.f("fk_message_feedback_message_id_messages"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_id"],
            ["users.id"],
            name=op.f("fk_message_feedback_reviewer_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_message_feedback_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_message_feedback")),
        sa.UniqueConstraint(
            "message_id",
            "reviewer_id",
            name=op.f("uq_message_feedback_message_id_reviewer_id"),
        ),
    )
    op.create_index(
        op.f("ix_message_feedback_message_id"),
        "message_feedback",
        ["message_id"],
    )
    op.create_index(
        op.f("ix_message_feedback_workspace_id"),
        "message_feedback",
        ["workspace_id"],
    )
    op.execute("ALTER TABLE message_feedback ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY message_feedback_workspace_isolation ON message_feedback "
        f"USING ({_PREDICATE}) WITH CHECK ({_PREDICATE})"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS message_feedback_workspace_isolation ON message_feedback")
    op.drop_index(op.f("ix_message_feedback_workspace_id"), table_name="message_feedback")
    op.drop_index(op.f("ix_message_feedback_message_id"), table_name="message_feedback")
    op.drop_table("message_feedback")
    sa.Enum(name="feedback_rating").drop(op.get_bind(), checkfirst=True)
