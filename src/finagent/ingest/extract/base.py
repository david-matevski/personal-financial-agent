"""Extraction backend contract.

Text-layer PDF parsing (pdfplumber) is tried first; OCR is a fallback for
pages with no usable text layer. Both implement this same Protocol so the
rest of the pipeline is agnostic to which backend produced the text
(AGENTS.md §3: "OCR backend is swappable behind a Protocol").
"""

from typing import Protocol


class TextExtractor(Protocol):
    """Extracts per-page text from a source document."""

    def extract(self, pdf_bytes: bytes) -> list[str]:
        """Return one string of extracted text per page, in page order."""
        ...
