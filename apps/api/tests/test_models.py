"""Schema-shape tests that need no database."""

import app.db.models  # noqa: F401 - registers every table
from app.db.base import Base
from app.db.models.enums import AnswerDecision, AnswerStatus, ClaimVerdict
from app.decision.types import DecisionOutcome
from app.rag.types import AnswerOutcome
from app.rag.types import ClaimVerdict as RagClaimVerdict

EXPECTED_TABLES = {
    "audit_logs",
    "chunk_embeddings",
    "chunks",
    "citations",
    "conversations",
    "document_versions",
    "documents",
    "ingestion_jobs",
    "memberships",
    "message_feedback",
    "messages",
    "pages",
    "refresh_tokens",
    "storage_purges",
    "users",
    "verification_results",
    "workspaces",
}

WORKSPACE_OWNED_TABLES = {
    "chunk_embeddings",
    "chunks",
    "conversations",
    "documents",
    "ingestion_jobs",
    "message_feedback",
    # Outlives the document it describes, but still tenant-owned: the sweeper
    # reads across workspaces and row-level security must still fence it.
    "storage_purges",
}


def test_all_initial_tables_are_registered() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_tenant_tables_declare_workspace_ownership() -> None:
    for name in WORKSPACE_OWNED_TABLES:
        column = Base.metadata.tables[name].columns["workspace_id"]
        assert not column.nullable, name
        targets = {fk.target_fullname for fk in column.foreign_keys}
        assert targets == {"workspaces.id"}, name


def test_constraint_names_follow_the_naming_convention() -> None:
    users = Base.metadata.tables["users"]
    assert users.primary_key.name == "pk_users"


def test_persisted_decision_mirrors_the_policy_vocabulary() -> None:
    """The ORM enum and the decision policy's own enum must agree by value.

    They are deliberately separate types so the policy never imports the ORM,
    and `app.conversations.service` converts between them *by value*. A member
    added to one side and not the other would therefore raise `ValueError` when
    an answer is persisted — at the point of writing a real thread, not here.
    """
    assert {member.value for member in AnswerDecision} == {
        member.value for member in DecisionOutcome
    }


def test_persisted_answer_status_mirrors_the_pipeline_vocabulary() -> None:
    assert {member.value for member in AnswerStatus} == {member.value for member in AnswerOutcome}


def test_persisted_verdict_mirrors_the_pipeline_vocabulary() -> None:
    assert {member.value for member in ClaimVerdict} == {member.value for member in RagClaimVerdict}


def test_a_message_bounds_its_confidence() -> None:
    """A stored confidence outside [0, 1] is not a low score; it is a bug."""
    constraints = {constraint.name for constraint in Base.metadata.tables["messages"].constraints}
    assert "ck_messages_confidence_range" in constraints


def test_audit_logs_are_append_only_shaped() -> None:
    audit = Base.metadata.tables["audit_logs"]
    assert "updated_at" not in audit.columns
    assert audit.columns["workspace_id"].nullable
    assert audit.columns["actor_user_id"].nullable
