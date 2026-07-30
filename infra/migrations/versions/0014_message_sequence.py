"""An explicit turn position on messages.

`created_at` cannot order the turns of a thread. A question and its answer are
written in one transaction, and PostgreSQL's `now()` is transaction-start time,
so both rows receive the same timestamp and SQL is then free to return the
answer before the question that produced it. `sequence` makes the order a
recorded fact instead of an accident of timestamp resolution.

Unique per conversation, so two concurrent turns cannot claim the same position;
the writer takes the conversation's row lock before choosing a number.

Existing rows default to 0. No deployment has written conversation turns yet —
the endpoints are new in this change — so there is nothing to renumber.

Revision ID: 0014
Revises: 0013
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("sequence", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.create_unique_constraint(
        op.f("uq_messages_conversation_id_sequence"),
        "messages",
        ["conversation_id", "sequence"],
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("uq_messages_conversation_id_sequence"),
        "messages",
        type_="unique",
    )
    op.drop_column("messages", "sequence")
