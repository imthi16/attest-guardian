"""The claim a citation supports, recorded rather than inferred.

A citation and its claim verdict are written together, but they are read back
through two independent relationships with no ordering guarantee. A client that
paired them by list position would, for a multi-claim answer, eventually show one
claim's passage underneath another claim — the evidence would look proven and be
attached to the wrong statement. `claim_index` makes the association a stored
fact, matching `verification_results.claim_index` on the same message, and the
unique constraint keeps one claim from collecting two citations.

Existing rows are numbered by insertion order within their message, which both
satisfies the constraint and is the order they were written in. No deployment has
answered a question yet — the conversation endpoints are new — so there is no
real thread whose pairing this could get wrong.

Revision ID: 0015
Revises: 0014
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "citations",
        sa.Column("claim_index", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.execute(
        sa.text(
            """
            UPDATE citations AS c
            SET claim_index = numbered.position
            FROM (
                SELECT
                    id,
                    ROW_NUMBER() OVER (
                        PARTITION BY message_id ORDER BY created_at, id
                    ) - 1 AS position
                FROM citations
            ) AS numbered
            WHERE numbered.id = c.id
            """
        )
    )
    # The default existed only to backfill; a new citation must state which claim
    # it supports rather than silently landing on claim zero.
    op.alter_column("citations", "claim_index", server_default=None)
    op.create_unique_constraint(
        op.f("uq_citations_message_id_claim_index"),
        "citations",
        ["message_id", "claim_index"],
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("uq_citations_message_id_claim_index"),
        "citations",
        type_="unique",
    )
    op.drop_column("citations", "claim_index")
