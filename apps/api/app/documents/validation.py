"""Upload validation: filenames, types, declared MIME, and content sniffing.

Uploaded files are untrusted input. Nothing here trusts what the client
declares: the extension must be an allowed type, the declared MIME must match
that type, and the bytes themselves must look like the type claims (magic
numbers for PDF/DOCX, valid UTF-8 without NULs for text). Failures raise
`UploadRejectedError` with a stable machine-readable code.
"""

import enum
import io
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath


class UploadRejectedError(Exception):
    """The upload violates a validation rule; `code` is a stable error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class DocumentKind(enum.Enum):
    PDF = "pdf"
    TEXT = "text"
    MARKDOWN = "markdown"
    DOCX = "docx"


_EXTENSION_KINDS: dict[str, DocumentKind] = {
    ".pdf": DocumentKind.PDF,
    ".txt": DocumentKind.TEXT,
    ".md": DocumentKind.MARKDOWN,
    ".markdown": DocumentKind.MARKDOWN,
    ".docx": DocumentKind.DOCX,
}

CANONICAL_MIME: dict[DocumentKind, str] = {
    DocumentKind.PDF: "application/pdf",
    DocumentKind.TEXT: "text/plain",
    DocumentKind.MARKDOWN: "text/markdown",
    DocumentKind.DOCX: ("application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
}

_ACCEPTED_MIME: dict[DocumentKind, frozenset[str]] = {
    DocumentKind.PDF: frozenset({"application/pdf"}),
    DocumentKind.TEXT: frozenset({"text/plain"}),
    DocumentKind.MARKDOWN: frozenset({"text/markdown", "text/plain"}),
    DocumentKind.DOCX: frozenset(
        {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
    ),
}

MAX_FILENAME_LENGTH = 255


@dataclass(frozen=True)
class ValidatedUpload:
    """The outcome of full validation: safe name, true kind, canonical MIME."""

    filename: str
    kind: DocumentKind
    canonical_mime: str


def sanitize_filename(raw_filename: str | None) -> str:
    """Return a safe basename or reject; path components are never trusted."""
    if not raw_filename:
        raise UploadRejectedError("invalid_filename", "A filename is required.")
    # Take the basename under both path conventions so traversal cannot hide.
    basename = PurePosixPath(PureWindowsPath(raw_filename.strip()).name).name
    if not basename or basename in {".", ".."}:
        raise UploadRejectedError("invalid_filename", "The filename is empty or a path.")
    if len(basename) > MAX_FILENAME_LENGTH:
        raise UploadRejectedError("invalid_filename", "The filename is too long.")
    if any(ord(char) < 32 or char == "\x7f" for char in basename):
        raise UploadRejectedError("invalid_filename", "The filename contains control characters.")
    return basename


def detect_kind(filename: str) -> DocumentKind:
    suffix = PurePosixPath(filename).suffix.lower()
    kind = _EXTENSION_KINDS.get(suffix)
    if kind is None:
        raise UploadRejectedError(
            "unsupported_file_type",
            "Only PDF, TXT, Markdown, and DOCX files are supported.",
        )
    return kind


def check_declared_mime(kind: DocumentKind, declared_mime: str | None) -> None:
    normalized = (declared_mime or "").split(";")[0].strip().lower()
    if normalized not in _ACCEPTED_MIME[kind]:
        raise UploadRejectedError(
            "mime_mismatch",
            "The declared content type does not match the file extension.",
        )


def verify_content(kind: DocumentKind, data: bytes) -> None:
    """The bytes must actually be what the name and MIME claim."""
    if not data:
        raise UploadRejectedError("empty_file", "The file is empty.")
    if kind is DocumentKind.PDF:
        if not data.startswith(b"%PDF-"):
            raise UploadRejectedError("content_mismatch", "The file is not a valid PDF.")
    elif kind is DocumentKind.DOCX:
        if not _looks_like_docx(data):
            raise UploadRejectedError("content_mismatch", "The file is not a valid DOCX archive.")
    else:
        if b"\x00" in data:
            raise UploadRejectedError("content_mismatch", "Text files must not contain NUL bytes.")
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            raise UploadRejectedError(
                "content_mismatch",
                "Text files must be valid UTF-8.",
            ) from None


def _looks_like_docx(data: bytes) -> bool:
    if not data.startswith(b"PK\x03\x04"):
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return "[Content_Types].xml" in archive.namelist()
    except zipfile.BadZipFile:
        return False


def validate_upload(
    raw_filename: str | None,
    declared_mime: str | None,
    data: bytes,
) -> ValidatedUpload:
    """Run every rule; any failure raises `UploadRejectedError`."""
    filename = sanitize_filename(raw_filename)
    kind = detect_kind(filename)
    check_declared_mime(kind, declared_mime)
    verify_content(kind, data)
    return ValidatedUpload(filename=filename, kind=kind, canonical_mime=CANONICAL_MIME[kind])
