"""Repository behavior, tenancy scoping, and database constraints."""

import pytest
from app.db.models import (
    Chunk,
    Document,
    DocumentStatus,
    Membership,
    MembershipRole,
    User,
    VerificationResult,
    Workspace,
)
from app.db.models.enums import ClaimVerdict
from app.db.repositories import (
    AuditLogRepository,
    DocumentRepository,
    MembershipRepository,
    UserRepository,
    WorkspaceRepository,
)
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.factories import (
    make_chunk,
    make_citation,
    make_conversation_with_answer,
    make_document,
    make_user,
    make_version,
    make_workspace,
)


async def test_user_repository_roundtrip_and_email_lookup(db_session: AsyncSession) -> None:
    repository = UserRepository(db_session)
    user = await make_user(db_session, email="lookup@example.test")

    assert await repository.get(user.id) is not None
    found = await repository.get_by_email("lookup@example.test")
    assert found is not None
    assert found.id == user.id
    assert await repository.get_by_email("absent@example.test") is None

    await repository.delete(user)
    assert await repository.get(user.id) is None


async def test_duplicate_email_is_rejected(db_session: AsyncSession) -> None:
    await make_user(db_session, email="unique@example.test")
    with pytest.raises(IntegrityError):
        await make_user(db_session, email="unique@example.test")


async def test_workspace_slug_lookup_and_membership_uniqueness(
    db_session: AsyncSession,
) -> None:
    owner = await make_user(db_session)
    workspace = await make_workspace(db_session, owner)

    workspaces = WorkspaceRepository(db_session)
    found = await workspaces.get_by_slug(workspace.slug)
    assert found is not None
    assert found.id == workspace.id

    memberships = MembershipRepository(db_session)
    membership = await memberships.get_membership(workspace.id, owner.id)
    assert membership is not None
    assert membership.role is MembershipRole.OWNER
    assert len(await memberships.list_for_workspace(workspace.id)) == 1

    with pytest.raises(IntegrityError):
        await memberships.add(
            Membership(
                workspace_id=workspace.id,
                user_id=owner.id,
                role=MembershipRole.VIEWER,
            )
        )


async def test_workspace_scoping_blocks_cross_tenant_access(
    db_session: AsyncSession,
) -> None:
    owner = await make_user(db_session)
    workspace_a = await make_workspace(db_session, owner)
    workspace_b = await make_workspace(db_session, owner)
    document_a = await make_document(db_session, workspace_a, owner)
    document_b = await make_document(db_session, workspace_b, owner)

    scoped_to_a = DocumentRepository(db_session, workspace_a.id)
    assert await scoped_to_a.get(document_a.id) is not None
    assert await scoped_to_a.get(document_b.id) is None

    listed = await scoped_to_a.list_all()
    assert [item.id for item in listed] == [document_a.id]

    foreign_document = Document(
        workspace_id=workspace_b.id,
        created_by=owner.id,
        title="Wrong tenant",
        source_filename="wrong.pdf",
        mime_type="application/pdf",
        size_bytes=1,
        sha256="d" * 64,
    )
    with pytest.raises(ValueError, match="different workspace"):
        await scoped_to_a.add(foreign_document)

    own_document = Document(
        workspace_id=workspace_a.id,
        created_by=owner.id,
        title="Right tenant",
        source_filename="right.pdf",
        mime_type="application/pdf",
        size_bytes=1,
        sha256="e" * 64,
    )
    added = await scoped_to_a.add(own_document)
    assert await scoped_to_a.get(added.id) is not None


async def test_document_status_defaults_and_filtering(db_session: AsyncSession) -> None:
    owner = await make_user(db_session)
    workspace = await make_workspace(db_session, owner)
    document = await make_document(db_session, workspace, owner)
    assert document.status is DocumentStatus.PENDING

    repository = DocumentRepository(db_session, workspace.id)
    assert len(await repository.list_by_status(DocumentStatus.PENDING)) == 1
    assert len(await repository.list_by_status(DocumentStatus.READY)) == 0


async def test_chunk_span_check_constraint(db_session: AsyncSession) -> None:
    owner = await make_user(db_session)
    workspace = await make_workspace(db_session, owner)
    document = await make_document(db_session, workspace, owner)
    version = await make_version(db_session, document)

    with pytest.raises(IntegrityError):
        await make_chunk(db_session, workspace, version, char_start=10, char_end=10)


async def test_cited_chunks_cannot_be_deleted(db_session: AsyncSession) -> None:
    owner = await make_user(db_session)
    workspace = await make_workspace(db_session, owner)
    document = await make_document(db_session, workspace, owner)
    version = await make_version(db_session, document)
    chunk = await make_chunk(db_session, workspace, version)
    message = await make_conversation_with_answer(db_session, workspace, owner)
    await make_citation(db_session, message, chunk)

    with pytest.raises(IntegrityError):
        await db_session.execute(delete(Chunk).where(Chunk.id == chunk.id))


async def test_verification_confidence_range_is_enforced(db_session: AsyncSession) -> None:
    owner = await make_user(db_session)
    workspace = await make_workspace(db_session, owner)
    message = await make_conversation_with_answer(db_session, workspace, owner)

    db_session.add(
        VerificationResult(
            message_id=message.id,
            claim_index=0,
            claim_text="A synthetic claim.",
            verdict=ClaimVerdict.SUPPORTED,
            confidence=1.5,
            verifier="unit-verifier",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_workspace_deletion_cascades_to_owned_rows(db_session: AsyncSession) -> None:
    owner = await make_user(db_session)
    workspace = await make_workspace(db_session, owner)
    document = await make_document(db_session, workspace, owner)
    version = await make_version(db_session, document)
    await make_chunk(db_session, workspace, version)

    await db_session.execute(delete(Workspace).where(Workspace.id == workspace.id))

    remaining_documents = await db_session.scalars(
        select(Document).where(Document.workspace_id == workspace.id)
    )
    assert remaining_documents.all() == []
    remaining_chunks = await db_session.scalars(
        select(Chunk).where(Chunk.workspace_id == workspace.id)
    )
    assert remaining_chunks.all() == []


async def test_creator_of_workspace_cannot_be_deleted(db_session: AsyncSession) -> None:
    owner = await make_user(db_session)
    await make_workspace(db_session, owner)

    with pytest.raises(IntegrityError):
        await db_session.execute(delete(User).where(User.id == owner.id))


async def test_audit_log_is_append_only(db_session: AsyncSession) -> None:
    owner = await make_user(db_session)
    workspace = await make_workspace(db_session, owner)
    repository = AuditLogRepository(db_session)

    entry = await repository.record(
        action="workspace.created",
        resource_type="workspace",
        resource_id=workspace.id,
        workspace_id=workspace.id,
        actor_user_id=owner.id,
        detail={"slug": workspace.slug},
    )
    assert entry.detail == {"slug": workspace.slug}
    assert entry.created_at is not None

    with pytest.raises(NotImplementedError):
        await repository.delete(entry)
