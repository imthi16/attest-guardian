"""In-memory PDF fixture builders (reportlab); no binary fixtures in git."""

import io

from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas


def digital_pdf(*page_texts: str) -> bytes:
    """A digital PDF with one page per string; empty strings make blank pages."""
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=LETTER)
    for text in page_texts:
        if text:
            writer = pdf.beginText(72, 720)
            for line in text.splitlines():
                writer.textLine(line)
            pdf.drawText(writer)
        pdf.showPage()
    pdf.save()
    return buffer.getvalue()
