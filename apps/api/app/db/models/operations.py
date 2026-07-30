"""Audit logs and asynchronous ingestion jobs."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base, UUIDPrimaryKeyMixin, WorkspaceOwnedModel
from app.db.models.enums import IngestionStage, IngestionStatus, pg_enum


class AuditLog(UUIDPrimaryKeyMixin, Base):
    """Append-only record of security-relevant decisions; rows are never updated.

    Workspace and actor references are nullable with `SET NULL` so audit
    history outlives the entities it describes.
    """

    __tablename__ = "audit_logs"

    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="SET NULL"),
        index=True,
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    action: Mapped[str] = mapped_column(String(100))
    resource_type: Mapped[str] = mapped_column(String(100))
    resource_id: Mapped[uuid.UUID | None] = mapped_column()
    detail: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
    )


class StoragePurge(WorkspaceOwnedModel):
    """A committed instruction to remove one deleted document's stored bytes.

    Permanent deletion cannot delete database rows and object-storage keys in
    one transaction, so it does not try: it commits the row deletion together
    with this record and performs no storage call at all. A sweeper
    (`app.documents.purge`) then deletes the objects and marks the record done,
    retrying until it succeeds — so a crash or a storage outage delays the purge
    instead of stranding a document that still issues download links for bytes
    that are already gone.

    `key_prefix` is the authority on what to remove, not `keys`: page images
    reach storage before their `pages` rows are committed, so a run that failed
    mid-OCR leaves content no row ever recorded. `keys` carries what the rows
    did know, so a listing failure still purges the uploaded bytes.
    """

    __tablename__ = "storage_purges"

    # Deliberately not a foreign key: the document row is gone by the time this
    # record matters, and the purge must outlive it.
    document_id: Mapped[uuid.UUID] = mapped_column(index=True)
    key_prefix: Mapped[str] = mapped_column(Text)
    keys: Mapped[list[str]] = mapped_column(
        JSONB,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    last_error: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IngestionJob(WorkspaceOwnedModel):
    """Tracks one asynchronous document-processing run."""

    __tablename__ = "ingestion_jobs"

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"),
        index=True,
    )
    document_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"),
    )
    status: Mapped[IngestionStatus] = mapped_column(
        pg_enum(IngestionStatus, "ingestion_status"),
        default=IngestionStatus.QUEUED,
    )
    stage: Mapped[IngestionStage] = mapped_column(
        pg_enum(IngestionStage, "ingestion_stage"),
        default=IngestionStage.UPLOADED,
        server_default=IngestionStage.UPLOADED.value,
    )
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    error: Mapped[str | None] = mapped_column(Text)
    # Whether the failure was deterministic rather than transient. The worker
    # maps both kinds to `FAILED`, but only a transient failure can plausibly
    # succeed on the same bytes; a hash mismatch, an unparseable file, or a
    # provenance violation will fail identically every time, so retry refuses
    # them instead of letting a caller queue unbounded doomed runs.
    permanent_failure: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=text("false"),
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
