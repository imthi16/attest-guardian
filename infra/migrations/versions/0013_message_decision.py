"""Keep the whole grounding verdict on an assistant turn, not just its status.

`messages.answer_status` records whether an answer was produced; it does not
record what the platform decided to do about it. Three different decisions —
no usable evidence, a question that needs narrowing, and evidence that
contradicts itself — all surface as `abstained`, so a stored thread carrying
only the status cannot tell a reader which happened, or that a human was asked
to review. The live response has always carried all four values; persisting
them is what makes a reloaded thread say the same thing as the answer did.

Every column is nullable: a user turn has no verdict of its own, and rows
written before this migration have none either. Backfilling is not possible and
not attempted — the decision was never stored, so inventing one would be worse
than an honest null.

Revision ID: 0013
Revises: 0012
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DECISIONS = (
    "answer",
    "answer_with_warning",
    "ask_for_clarification",
    "abstain",
    "escalate_for_review",
)


def upgrade() -> None:
    # `add_column` does not create the type the way `create_table` does, so the
    # enum is created explicitly first and the column told not to repeat it.
    decision_enum = postgresql.ENUM(*_DECISIONS, name="answer_decision")
    decision_enum.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "messages",
        sa.Column(
            "decision",
            sa.Enum(*_DECISIONS, name="answer_decision", create_type=False),
            nullable=True,
        ),
    )
    op.add_column("messages", sa.Column("decision_reason", sa.Text(), nullable=True))
    op.add_column("messages", sa.Column("confidence", sa.Float(), nullable=True))
    op.add_column("messages", sa.Column("abstention_reason", sa.String(length=100), nullable=True))
    # Mirrors the bound on `verification_results.confidence`. Nullable passes,
    # so a user turn is unaffected.
    # Named as the metadata's convention resolves it, written out explicitly as
    # migration 0001 does for the other check constraints.
    op.create_check_constraint(
        "ck_messages_confidence_range",
        "messages",
        "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_messages_confidence_range", "messages", type_="check")
    op.drop_column("messages", "abstention_reason")
    op.drop_column("messages", "confidence")
    op.drop_column("messages", "decision_reason")
    op.drop_column("messages", "decision")
    postgresql.ENUM(name="answer_decision").drop(op.get_bind(), checkfirst=True)
