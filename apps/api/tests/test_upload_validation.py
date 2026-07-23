"""Upload validation rules: every spoofing path must be rejected."""

import io
import zipfile

import pytest
from app.documents.validation import (
    DocumentKind,
    UploadRejectedError,
    check_declared_mime,
    detect_kind,
    sanitize_filename,
    validate_upload,
    verify_content,
)

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def make_docx_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<w:document/>")
    return buffer.getvalue()


def code_of(error: pytest.ExceptionInfo[UploadRejectedError]) -> str:
    return error.value.code


class TestFilenames:
    def test_plain_names_pass(self) -> None:
        assert sanitize_filename("report.pdf") == "report.pdf"

    def test_tamil_names_pass(self) -> None:
        assert sanitize_filename("ஆவணம்.pdf") == "ஆவணம்.pdf"

    def test_path_traversal_is_stripped(self) -> None:
        assert sanitize_filename("../../etc/passwd.pdf") == "passwd.pdf"
        assert sanitize_filename("..\\..\\windows\\evil.pdf") == "evil.pdf"

    @pytest.mark.parametrize("bad", [None, "", "   ", ".", "..", "a\x00b.pdf", "a\nb.pdf"])
    def test_bad_names_are_rejected(self, bad: str | None) -> None:
        with pytest.raises(UploadRejectedError) as error:
            sanitize_filename(bad)
        assert code_of(error) == "invalid_filename"

    def test_overlong_names_are_rejected(self) -> None:
        with pytest.raises(UploadRejectedError):
            sanitize_filename("a" * 300 + ".pdf")


class TestKindDetection:
    @pytest.mark.parametrize(
        ("filename", "kind"),
        [
            ("a.pdf", DocumentKind.PDF),
            ("a.PDF", DocumentKind.PDF),
            ("a.txt", DocumentKind.TEXT),
            ("a.md", DocumentKind.MARKDOWN),
            ("a.markdown", DocumentKind.MARKDOWN),
            ("a.docx", DocumentKind.DOCX),
        ],
    )
    def test_allowed_extensions(self, filename: str, kind: DocumentKind) -> None:
        assert detect_kind(filename) is kind

    @pytest.mark.parametrize("filename", ["a.exe", "a.pdf.exe", "a.html", "noext", "a.doc"])
    def test_disallowed_extensions(self, filename: str) -> None:
        with pytest.raises(UploadRejectedError) as error:
            detect_kind(filename)
        assert code_of(error) == "unsupported_file_type"


class TestDeclaredMime:
    def test_matching_mime_passes(self) -> None:
        check_declared_mime(DocumentKind.PDF, "application/pdf")
        check_declared_mime(DocumentKind.MARKDOWN, "text/plain")
        check_declared_mime(DocumentKind.MARKDOWN, "text/markdown; charset=utf-8")
        check_declared_mime(DocumentKind.DOCX, DOCX_MIME)

    @pytest.mark.parametrize(
        ("kind", "declared"),
        [
            (DocumentKind.PDF, "text/plain"),
            (DocumentKind.PDF, "application/octet-stream"),
            (DocumentKind.PDF, None),
            (DocumentKind.TEXT, "text/markdown"),
            (DocumentKind.DOCX, "application/zip"),
        ],
    )
    def test_mismatched_mime_is_rejected(self, kind: DocumentKind, declared: str | None) -> None:
        with pytest.raises(UploadRejectedError) as error:
            check_declared_mime(kind, declared)
        assert code_of(error) == "mime_mismatch"


class TestContentSniffing:
    def test_real_pdf_passes(self) -> None:
        verify_content(DocumentKind.PDF, b"%PDF-1.7 fake body")

    def test_non_pdf_bytes_with_pdf_kind_are_rejected(self) -> None:
        with pytest.raises(UploadRejectedError) as error:
            verify_content(DocumentKind.PDF, b"MZ\x90\x00 executable")
        assert code_of(error) == "content_mismatch"

    def test_real_docx_passes(self) -> None:
        verify_content(DocumentKind.DOCX, make_docx_bytes())

    @pytest.mark.parametrize(
        "payload",
        [b"not a zip", b"PK\x03\x04 truncated zip"],
    )
    def test_fake_docx_is_rejected(self, payload: bytes) -> None:
        with pytest.raises(UploadRejectedError) as error:
            verify_content(DocumentKind.DOCX, payload)
        assert code_of(error) == "content_mismatch"

    def test_zip_without_content_types_is_rejected(self) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("innocent.txt", "hello")
        with pytest.raises(UploadRejectedError):
            verify_content(DocumentKind.DOCX, buffer.getvalue())

    def test_utf8_text_passes_including_tamil(self) -> None:
        verify_content(DocumentKind.TEXT, "வணக்கம் உலகம்".encode())

    def test_invalid_utf8_is_rejected(self) -> None:
        with pytest.raises(UploadRejectedError) as error:
            verify_content(DocumentKind.TEXT, b"\xff\xfe broken")
        assert code_of(error) == "content_mismatch"

    def test_nul_bytes_in_text_are_rejected(self) -> None:
        with pytest.raises(UploadRejectedError):
            verify_content(DocumentKind.MARKDOWN, b"hello\x00world")

    def test_empty_file_is_rejected(self) -> None:
        with pytest.raises(UploadRejectedError) as error:
            verify_content(DocumentKind.TEXT, b"")
        assert code_of(error) == "empty_file"


def test_validate_upload_happy_path() -> None:
    validated = validate_upload("notes.md", "text/markdown", "# தலைப்பு".encode())
    assert validated.kind is DocumentKind.MARKDOWN
    assert validated.canonical_mime == "text/markdown"
    assert validated.filename == "notes.md"
