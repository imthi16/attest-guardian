"""The committed OpenAPI document must describe the application as it is.

`packages/contracts/openapi.json` is what the web app's schema-drift test reads.
A stale copy would let both sides pass while disagreeing with reality — the
worst of the three outcomes, because it looks like the check is working.

So the file is regenerated and compared here. A response model that gains,
loses, or renames a field fails this test with the instruction to regenerate,
and the regenerated diff then either passes the web check or fails it, which is
the point.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from app.contracts import build_schema, contracts_dir, render, schema_path, write

COMMITTED = schema_path().read_text(encoding="utf-8")
SCHEMA = build_schema()


def test_the_committed_schema_matches_the_application() -> None:
    assert COMMITTED == render(), (
        "packages/contracts/openapi.json is stale. Regenerate it with "
        "`make contracts` and review the diff: it is the contract the web app "
        "is checked against."
    )


def test_the_schema_omits_the_release_version() -> None:
    """A release bump is not a contract change and must not read as one.

    Leaving `info.version` in would make the drift check fire on every release,
    and a check that cries wolf is one people learn to regenerate without
    reading.
    """
    assert "version" not in SCHEMA.get("info", {})


def test_every_response_the_web_mirrors_is_present() -> None:
    """Named here so deleting one fails on this side too, with a reason.

    Without it, removing a response model would fail only in the web suite, as a
    missing-key error in a file whose author had no reason to expect it.
    """
    mirrored = {
        "CitationRecordResponse",
        "ClaimRecordResponse",
        "ConversationDetailResponse",
        "ConversationResponse",
        "DocumentProgressResponse",
        "DocumentResponse",
        "DownloadLinkResponse",
        "FeedbackResponse",
        "MemberResponse",
        "MessageResponse",
        "ResolvedCitationResponse",
        "TokenPairResponse",
        "UploadPolicyResponse",
        "UserResponse",
        "WorkspaceWithRoleResponse",
    }

    assert mirrored <= set(SCHEMA["components"]["schemas"])


def test_the_schema_describes_the_versioned_surface() -> None:
    paths = SCHEMA["paths"]

    assert any(path.startswith("/api/v1/auth/") for path in paths)
    assert any("/conversations" in path for path in paths)
    assert any("/citations/resolve" in path for path in paths)
    # Health is deliberately unversioned, so it must not sit under /api/v1 only.
    assert "/health" in paths


def test_the_schema_carries_no_credential_or_hostname() -> None:
    """It is committed and published, so it must not leak deployment detail.

    FastAPI derives the document from types and docstrings, so nothing should
    reach it — but this is a file that gets copied into clients and reviewed by
    people outside the deployment, and the cost of checking is one assertion.
    """
    text = render().lower()

    for leak in ("password=", "secret_key", "minio123", "postgresql://", "redis://"):
        assert leak not in text, leak


def test_writing_the_schema_is_idempotent(tmp_path: Path) -> None:
    """`make contracts` twice must produce one file, not a diff each time.

    Sorted keys and a fixed indent are what make the committed document
    reviewable: an unstable serialization would show a large diff on every
    regeneration, and a large diff is one nobody reads.
    """
    root = tmp_path / "repo"
    (root / "packages" / "contracts").mkdir(parents=True)
    (root / "AGENTS.md").write_text("marker", encoding="utf-8")
    start = root / "packages" / "contracts" / "probe.py"

    first = write(start)
    contents = first.read_text(encoding="utf-8")
    second = write(start)

    assert first == second
    assert second.read_text(encoding="utf-8") == contents


def test_an_unreachable_repository_root_is_an_explicit_error(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="repository root not found"):
        contracts_dir(tmp_path / "nowhere")
