"""Tests for the Tesseract OCR backend.

Most fallback-decision logic is covered with a fake extractor in
test_fallback.py. This file exercises the real Tesseract backend, skipped
when the tesseract binary isn't installed.
"""

import shutil

import pytest
from fpdf import FPDF

from finagent.ingest.extract.ocr import TesseractOcrExtractor


def _build_pdf_with_text(line: str) -> bytes:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=24)
    pdf.cell(0, 10, text=line)
    return bytes(pdf.output())


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract binary not installed")
def test_ocr_extracts_text_from_rendered_page() -> None:
    pdf_bytes = _build_pdf_with_text("MADE UP MERCHANT")

    text = TesseractOcrExtractor().ocr_page(pdf_bytes, 0)

    assert "MADE UP MERCHANT" in text.upper()
