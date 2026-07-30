"""Migration 0015 must recover which claim each existing citation supports.

The column exists to stop a passage being shown under the wrong statement, so a
backfill that guesses the association would ship the exact defect it prevents.
The rows are seeded at `0014` with raw SQL — the ORM models describe `head` and
cannot write a table that has no `claim_index` column yet — and deliberately
inserted so that no ordering recovers the pairing: the two citations of a turn
are written in one statement, so they share a `created_at`, they carry random
UUIDs, and they are written in the opposite order to the claims they support.
"""

import asyncio
import uuid

from tests.integration.dbtools import (
    MIGRATION_TEST_DB,
    Statement,
    alembic,
    provision_database,
    rows,
    run_sql,
)

MESSAGE_ID = uuid.uuid4()
CHUNK_IDS = (uuid.uuid4(), uuid.uuid4())
FIRST_CLAIM = "The notice period is ninety days."
SECOND_CLAIM = "Payment is due within thirty days."

PAIRED_SQL = """
    SELECT c.claim_index, c.claim_text, c.chunk_id, v.claim_text AS verdict_claim
    FROM citations AS c
    JOIN verification_results AS v
        ON v.message_id = c.message_id AND v.claim_index = c.claim_index
    WHERE c.message_id = $1
    ORDER BY c.claim_index
"""

PLACED_SQL = """
    SELECT claim_index, claim_text FROM citations
    WHERE message_id = $1 ORDER BY claim_index
"""


def seed_at_0014(url: str) -> None:
    """One assistant turn with two claims, each with a citation and a verdict."""
    user_id, workspace_id = uuid.uuid4(), uuid.uuid4()
    document_id, version_id = uuid.uuid4(), uuid.uuid4()
    conversation_id = uuid.uuid4()

    statements: list[Statement] = [
        # `documents`, `chunks`, and `conversations` are fenced by row-level
        # security. The test role is a superuser and would bypass it, but binding
        # the workspace keeps the seed working either way rather than depending
        # on which role happens to run it.
        ("SELECT set_config('app.workspace_id', $1, false)", [str(workspace_id)]),
        (
            """
            INSERT INTO users (id, email, password_hash, full_name)
            VALUES ($1, 'legacy@example.com', 'x', 'Legacy Reader')
            """,
            [user_id],
        ),
        (
            """
            INSERT INTO workspaces (id, name, slug, created_by)
            VALUES ($1, 'Legacy', 'legacy', $2)
            """,
            [workspace_id, user_id],
        ),
        (
            """
            INSERT INTO documents
                (id, workspace_id, created_by, title, source_filename, mime_type,
                 size_bytes, sha256)
            VALUES ($1, $2, $3, 'Lease', 'lease.pdf', 'application/pdf', 1024, $4)
            """,
            [document_id, workspace_id, user_id, "a" * 64],
        ),
        (
            """
            INSERT INTO document_versions
                (id, document_id, version_number, storage_key, sha256, size_bytes, page_count)
            VALUES ($1, $2, 1, 'documents/legacy.pdf', $3, 1024, 2)
            """,
            [version_id, document_id, "b" * 64],
        ),
    ]
    statements += [
        (
            """
            INSERT INTO chunks
                (id, workspace_id, document_version_id, chunk_index, content,
                 content_hash, page_number, char_start, char_end)
            VALUES ($1, $2, $3, $4, $5, $6, $7, 0, 10)
            """,
            [
                chunk_id,
                workspace_id,
                version_id,
                index,
                f"evidence {index}",
                f"{index:064x}",
                index + 1,
            ],
        )
        for index, chunk_id in enumerate(CHUNK_IDS)
    ]
    statements += [
        (
            """
            INSERT INTO conversations (id, workspace_id, created_by)
            VALUES ($1, $2, $3)
            """,
            [conversation_id, workspace_id, user_id],
        ),
        (
            """
            INSERT INTO messages (id, conversation_id, sequence, role, content)
            VALUES ($1, $2, 1, 'assistant', 'an answer')
            """,
            [MESSAGE_ID, conversation_id],
        ),
        # Written in the opposite order to the claims they support, and in one
        # statement so both rows share `created_at` — exactly the shape in which
        # row order carries no information about the pairing.
        (
            """
            INSERT INTO citations
                (id, message_id, chunk_id, claim_text, claim_start, claim_end,
                 quote_text, quote_start, quote_end, page_number)
            VALUES
                ($1, $2, $3, $4, 0, 33, 'thirty days', 0, 11, 2),
                ($5, $2, $6, $7, 0, 32, 'ninety days', 0, 11, 1)
            """,
            [
                uuid.uuid4(),
                MESSAGE_ID,
                CHUNK_IDS[1],
                SECOND_CLAIM,
                uuid.uuid4(),
                CHUNK_IDS[0],
                FIRST_CLAIM,
            ],
        ),
        (
            """
            INSERT INTO verification_results
                (id, message_id, chunk_id, claim_index, claim_text, verdict, confidence, verifier)
            VALUES
                ($1, $2, $3, 0, $4, 'supported', 0.9, 'entailment-verifier-v1'),
                ($5, $2, $6, 1, $7, 'supported', 0.85, 'entailment-verifier-v1')
            """,
            [
                uuid.uuid4(),
                MESSAGE_ID,
                CHUNK_IDS[0],
                FIRST_CLAIM,
                uuid.uuid4(),
                CHUNK_IDS[1],
                SECOND_CLAIM,
            ],
        ),
    ]
    asyncio.run(run_sql(url, statements))


def upgrade_to_0014_and_seed() -> str:
    url = provision_database(MIGRATION_TEST_DB)
    stopped = alembic(["upgrade", "0014"], url)
    assert stopped.returncode == 0, stopped.stderr
    seed_at_0014(url)
    return url


def test_backfill_pairs_each_citation_with_the_claim_it_supports() -> None:
    url = upgrade_to_0014_and_seed()

    upgraded = alembic(["upgrade", "0015"], url)
    assert upgraded.returncode == 0, upgraded.stderr

    paired = asyncio.run(rows(url, PAIRED_SQL, MESSAGE_ID))

    assert len(paired) == 2, "both citations must join a verdict on the backfilled index"
    for citation in paired:
        # The join is on the index alone, so matching texts prove the index
        # recovered the association rather than merely being distinct.
        assert citation["claim_text"] == citation["verdict_claim"]
    assert [citation["claim_text"] for citation in paired] == [FIRST_CLAIM, SECOND_CLAIM]
    # And the evidence still points where it did: index 0 keeps the chunk quoted
    # for the first claim, not the chunk whose citation row was written first.
    assert [citation["chunk_id"] for citation in paired] == list(CHUNK_IDS)


def test_backfill_parks_a_citation_whose_verdict_is_gone() -> None:
    """An unmatchable citation is paired with no claim rather than with claim 0.

    Claim 0 is a real statement. Defaulting an orphan onto it would attach
    evidence to an assertion it was never checked against — the failure the
    column exists to prevent — so it is parked above every index in use, where
    nothing renders it.
    """
    url = upgrade_to_0014_and_seed()
    asyncio.run(
        run_sql(
            url,
            [
                (
                    "DELETE FROM verification_results WHERE message_id = $1 AND claim_text = $2",
                    [MESSAGE_ID, SECOND_CLAIM],
                )
            ],
        )
    )

    upgraded = alembic(["upgrade", "0015"], url)
    assert upgraded.returncode == 0, upgraded.stderr

    placed = asyncio.run(rows(url, PLACED_SQL, MESSAGE_ID))

    assert placed[0] == {"claim_index": 0, "claim_text": FIRST_CLAIM}
    # Above claim 0, the only index this message actually uses.
    assert placed[1]["claim_text"] == SECOND_CLAIM
    assert isinstance(placed[1]["claim_index"], int)
    assert placed[1]["claim_index"] > 0
