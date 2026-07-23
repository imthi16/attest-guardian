"""Parser behavior: digital extraction, scanned detection, fallbacks."""

import io
import zipfile

import pytest
from app.parsing.pdf import parse_pdf, render_pdf_page_png
from app.parsing.text import parse_docx, parse_text
from app.parsing.types import ParserError

from tests.pdftools import digital_pdf

ENGLISH = "The quick brown fox reads Tamil documents.\nSecond line of evidence."


def test_digital_pdf_extracts_page_level_text() -> None:
    parsed = parse_pdf(digital_pdf(ENGLISH, "Page two content that is long enough."))
    assert parsed.parser == "pypdf"
    assert len(parsed.pages) == 2
    assert parsed.pages[0].page_number == 1
    assert "quick brown fox" in parsed.pages[0].text
    assert "Second line" in parsed.pages[0].text
    assert not parsed.pages[0].needs_ocr
    assert parsed.pages[1].page_number == 2


def test_blank_pages_are_flagged_as_scanned() -> None:
    parsed = parse_pdf(digital_pdf(""))
    assert len(parsed.pages) == 1
    assert parsed.pages[0].needs_ocr


def test_mixed_documents_flag_only_the_scanned_pages() -> None:
    parsed = parse_pdf(digital_pdf(ENGLISH, "", "Third page with plenty of real text here."))
    flags = [page.needs_ocr for page in parsed.pages]
    assert flags == [False, True, False]


def test_malformed_pdf_raises_parser_error() -> None:
    with pytest.raises(ParserError):
        parse_pdf(b"%PDF-1.4\nthis is not really a pdf body at all")


def test_render_page_produces_png() -> None:
    image = render_pdf_page_png(digital_pdf(ENGLISH), 1)
    assert image.startswith(b"\x89PNG\r\n")


def test_render_of_missing_page_raises() -> None:
    with pytest.raises(ParserError):
        render_pdf_page_png(digital_pdf(ENGLISH), 99)


def test_text_parsing_keeps_tamil_content() -> None:
    parsed = parse_text("வணக்கம் உலகம்\nஇரண்டாவது வரி".encode())
    assert parsed.parser == "text"
    assert parsed.pages[0].text.startswith("வணக்கம்")


def test_text_parsing_rejects_invalid_utf8() -> None:
    with pytest.raises(ParserError):
        parse_text(b"\xff\xfe broken")


def make_docx(paragraphs: list[str]) -> bytes:
    import docx

    buffer = io.BytesIO()
    document = docx.Document()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    document.save(buffer)
    return buffer.getvalue()


def test_docx_parsing_extracts_paragraphs_in_order() -> None:
    parsed = parse_docx(make_docx(["First paragraph.", "இரண்டாவது பத்தி."]))
    assert parsed.parser == "docx"
    assert parsed.pages[0].text == "First paragraph.\nஇரண்டாவது பத்தி."


def test_docx_parsing_rejects_garbage() -> None:
    broken = io.BytesIO()
    with zipfile.ZipFile(broken, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
    with pytest.raises(ParserError):
        parse_docx(broken.getvalue())
