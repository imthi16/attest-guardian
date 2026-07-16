"""Request and response bodies for document endpoints."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.db.models.enums import DocumentStatus


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


class DownloadLinkResponse(BaseModel):
    url: str
    expires_in_seconds: int
