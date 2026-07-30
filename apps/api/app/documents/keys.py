"""Server-generated object-storage keys for document content.

Keys are derived from identifiers the server chose — never from an uploaded
filename — and every object a document produces lives under one per-document
prefix: the uploaded bytes of each version and any page image rendered for OCR.

That layout is a contract, not a convenience. Permanent deletion purges the
prefix rather than replaying the rows it is about to destroy, so an object whose
database row was never committed — a page image written to storage just before
OCR failed — is still removed. Anything that writes document content must build
its key here so it stays inside the prefix a purge sweeps.
"""

import uuid


def document_prefix(workspace_id: uuid.UUID, document_id: uuid.UUID) -> str:
    """The prefix every stored object belonging to this document sits under."""
    return f"workspaces/{workspace_id}/documents/{document_id}/"


def version_key(
    workspace_id: uuid.UUID,
    document_id: uuid.UUID,
    *,
    version_number: int,
    sha256: str,
) -> str:
    """Key for one version's uploaded bytes; the hash prefix makes it unique."""
    return f"{document_prefix(workspace_id, document_id)}v{version_number}-{sha256[:16]}"


def page_image_key(
    workspace_id: uuid.UUID,
    document_id: uuid.UUID,
    *,
    version_number: int,
    page_number: int,
) -> str:
    """Key for one rendered page image (a picture of the document's content)."""
    return f"{document_prefix(workspace_id, document_id)}pages/v{version_number}/p{page_number}.png"


__all__ = ["document_prefix", "page_image_key", "version_key"]
