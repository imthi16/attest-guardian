"""Request and response bodies for document endpoints."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.db.models.enums import DocumentStatus, IngestionStage, IngestionStatus


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
