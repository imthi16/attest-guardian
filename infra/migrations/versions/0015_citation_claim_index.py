"""The claim a citation supports, recorded rather than inferred.

A citation and its claim verdict are written together, but they are read back
through two independent relationships with no ordering guarantee. A client that
paired them by list position would, for a multi-claim answer, eventually show one
claim's passage underneath another claim — the evidence would look proven and be
attached to the wrong statement. `claim_index` makes the association a stored
fact, matching `verification_results.claim_index` on the same message, and the
unique constraint keeps one claim from collecting two citations.

Existing rows are backfilled from the verdict they were written beside, matched on
`(message_id, claim_text)` — the association itself, since `app.conversations.
service` writes both rows from one claim and gives them the same text. Row order
is deliberately *not* used to infer it: the two rows of a turn are written in a
single transaction and therefore share `created_at`, while `id` is a random
UUID, so ordering by either would invent a pairing rather than recover one, and a
wrong pairing is the exact defect this column exists to prevent.

A citation the join cannot match — one whose verdict row is gone — keeps no
inferred association. It is given an index above every matched one on its
message, which satisfies the constraint and leaves it paired with no claim, so it
simply does not render rather than rendering under someone else's statement.

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
    # Added nullable and with no default, so "the backfill could not place this
    # row" stays distinguishable from "the backfill placed it at zero". A default
    # would make every unmatched row silently claim index 0 — the first claim's
    # position — which is the mis-pairing this column exists to rule out.
    op.add_column("citations", sa.Column("claim_index", sa.Integer(), nullable=True))
    # Matched on the claim text the two rows were written with. The slot columns
    # only disambiguate a message that repeated a claim verbatim: those citations
    # are interchangeable — either passage supports that exact text — so any
    # one-to-one assignment among them is correct, and ranking makes the choice
    # deterministic instead of leaving the join to multiply rows.
    op.execute(
        sa.text(
            """
            WITH ranked_citations AS (
                SELECT
                    id,
                    message_id,
                    claim_text,
                    ROW_NUMBER() OVER (
                        PARTITION BY message_id, claim_text ORDER BY id
                    ) AS slot
                FROM citations
            ),
            ranked_verdicts AS (
                SELECT
                    message_id,
                    claim_text,
                    claim_index,
                    ROW_NUMBER() OVER (
                        PARTITION BY message_id, claim_text ORDER BY claim_index
                    ) AS slot
                FROM verification_results
            )
            UPDATE citations AS c
            SET claim_index = ranked_verdicts.claim_index
            FROM ranked_citations
            JOIN ranked_verdicts
                ON ranked_verdicts.message_id = ranked_citations.message_id
                AND ranked_verdicts.claim_text = ranked_citations.claim_text
                AND ranked_verdicts.slot = ranked_citations.slot
            WHERE c.id = ranked_citations.id
            """
        )
    )
    # Whatever the join left unplaced is parked above every index its message
    # actually uses: the constraint is satisfied, and the row is paired with no
    # claim, so the UI shows it under none rather than under someone else's.
    op.execute(
        sa.text(
            """
            WITH orphans AS (
                SELECT
                    id,
                    message_id,
                    ROW_NUMBER() OVER (PARTITION BY message_id ORDER BY id) AS position
                FROM citations
                WHERE claim_index IS NULL
            )
            UPDATE citations AS c
            SET claim_index = orphans.position + COALESCE(
                (
                    SELECT MAX(placed.claim_index)
                    FROM citations AS placed
                    WHERE placed.message_id = orphans.message_id
                    AND placed.claim_index IS NOT NULL
                ),
                -1
            )
            FROM orphans
            WHERE c.id = orphans.id
            """
        )
    )
    # Every row now states which claim it supports, and a new one must too.
    op.alter_column("citations", "claim_index", nullable=False)
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
