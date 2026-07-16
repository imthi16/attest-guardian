"""OCR adapter behavior; the real Tesseract test runs where the binary exists."""

import io
import shutil

import pytest
from app.parsing.ocr import (
    NullOcrEngine,
    TesseractOcrEngine,
    build_ocr_engine,
)


async def test_null_engine_never_invents_text() -> None:
    result = await NullOcrEngine().recognize(b"png-bytes-irrelevant")
    assert result.text == ""
    assert result.confidence is None
    assert result.blocks == []


def test_engine_factory() -> None:
    assert isinstance(build_ocr_engine("none", "tam+eng"), NullOcrEngine)
    tesseract = build_ocr_engine("tesseract", "tam+eng")
    assert isinstance(tesseract, TesseractOcrEngine)
    assert tesseract.name == "tesseract"


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract binary not installed")
async def test_tesseract_recognizes_drawn_english_text() -> None:
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (900, 220), "white")
    draw = ImageDraw.Draw(image)
    draw.text((40, 60), "GUARDIAN EVIDENCE 2026", fill="black", font_size=64)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")

    result = await TesseractOcrEngine("eng").recognize(buffer.getvalue())
    assert "GUARDIAN" in result.text.upper()
    assert result.confidence is not None and 0 < result.confidence <= 1
    assert result.blocks, "word-level blocks with bounding boxes expected"
    first = result.blocks[0]
    assert first.bbox is not None and len(first.bbox) == 4
