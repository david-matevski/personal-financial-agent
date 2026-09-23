"""Extraction backend contracts.

Text-layer PDF parsing (pdfplumber) is tried first; OCR is a fallback for
pages with no usable text layer. Text extractors implement ``TextExtractor``
so the rest of the pipeline is agnostic to which backend produced the text
(AGENTS.md §3: "OCR backend is swappable behind a Protocol"). OCR is a
distinct, narrower role (``PageOcr``): it's only ever invoked one sparse
page at a time, never for a whole document.
"""

from typing import Protocol


class TextExtractor(Protocol):
    """Extracts per-page text from a source document."""

    def extract(self, pdf_bytes: bytes) -> list[str]:
        """Return one string of extracted text per page, in page order."""
        ...


class PageOcr(Protocol):
    """OCRs a single page of a document, by index."""

    def ocr_page(self, pdf_bytes: bytes, page_index: int) -> str:
        """Return the OCR'd text of the page at ``page_index`` (0-based)."""
        ...
