"""Request and response bodies for document endpoints."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from app.db.models.enums import DocumentStatus, IngestionStage, IngestionStatus

if TYPE_CHECKING:
    from app.db.models.documents import Document


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    source_filename: str
    mime_type: str
    size_bytes: int
    sha256: str
    status: DocumentStatus
    created_at: datetime
    archived_at: datetime | None
    # Whether *this* caller may ask for another ingestion run right now (see
    # `app.documents.lifecycle.may_retry`). Carried on the document itself, not
    # only on the progress endpoint, so a list can render the control without a
    # per-row request — and so it is never rendered from status alone, which
    # would offer a retry for a deterministic failure the endpoint refuses.
    #
    # The default is the safe answer: a route that does not compute it offers no
    # retry rather than promising one.
    retryable: bool = False

    @classmethod
    def of(cls, document: "Document", *, retryable: bool) -> "DocumentResponse":
        """Build the response for one document with its retry verdict attached."""
        response = cls.model_validate(document)
        response.retryable = retryable
        return response


class DownloadLinkResponse(BaseModel):
    url: str
    expires_in_seconds: int


class UploadPolicyResponse(BaseModel):
    """The limits this deployment actually enforces on uploads.

    Served so clients fail fast against the *deployed* configuration instead of
    a compiled-in copy of the defaults: `max_upload_bytes` is settable per
    environment, and a client mirroring only the default would reject files a
    raised limit allows, or promise files a lowered limit refuses.
    """

    max_upload_bytes: int
    max_filename_length: int
    accepted_extensions: list[str]


class DocumentProgressResponse(BaseModel):
    """Lifecycle progress: document status plus the latest ingestion run."""

    document_id: uuid.UUID
    status: DocumentStatus
    job_status: IngestionStatus | None
    stage: IngestionStage | None
    attempts: int
    error: str | None
    updated_at: datetime
    archived: bool
    # Whether *this* caller may ask for another ingestion run right now:
    # document state, the failure's permanence, and the caller's role together.
    # Computed from server state so the UI never has to reimplement the rule,
    # and scoped to the caller so it never offers an action they would be
    # refused.
    retryable: bool
