"""Composes text-layer extraction with a per-page OCR fallback.

Text-layer extraction (pdfplumber) is tried first for every page. A page
is only sent to OCR when its text layer yields fewer than
``MIN_TEXT_CHARS`` non-whitespace characters -- i.e. it's blank or
image-only. This keeps OCR (slow, lossy, and possibly unavailable) off the
common case of a normal digitally-generated statement, and off pages that
already have good text even when other pages in the same document don't.

If OCR can't run for a sparse page (missing optional deps, no Tesseract
binary, or a genuine per-page failure), that page's original sparse text
is kept and a warning is logged -- unless *every* page in the document was
sparse, in which case the whole document plainly needs OCR and we raise.
"""

import logging

from finagent.core.errors import ExtractionError
from finagent.ingest.extract.base import PageOcr, TextExtractor

logger = logging.getLogger(__name__)

MIN_TEXT_CHARS = 20


class FallbackTextExtractor:
    """Text-layer extraction with per-page OCR fallback for sparse pages."""

    def __init__(self, text_extractor: TextExtractor, page_ocr: PageOcr) -> None:
        self._text_extractor = text_extractor
        self._page_ocr = page_ocr

    def extract(self, pdf_bytes: bytes) -> list[str]:
        """Return one string per page, OCR'ing only pages with sparse text."""
        text_pages = self._text_extractor.extract(pdf_bytes)
        sparse_indices = [
            index for index, text in enumerate(text_pages) if len(text.strip()) < MIN_TEXT_CHARS
        ]
        if not sparse_indices:
            return text_pages

        pages = list(text_pages)
        failed_indices = []
        for index in sparse_indices:
            try:
                pages[index] = self._page_ocr.ocr_page(pdf_bytes, index)
            except ExtractionError:
                failed_indices.append(index)

        if failed_indices:
            all_pages_sparse = len(sparse_indices) == len(text_pages)
            if all_pages_sparse and len(failed_indices) == len(sparse_indices):
                raise ExtractionError(
                    "OCR failed and every page lacks a usable text layer "
                    f"(pages: {[i + 1 for i in failed_indices]})"
                )
            logger.warning(
                "OCR unavailable or failed for pages %s; keeping sparse text-layer output",
                [i + 1 for i in failed_indices],
            )

        return pages
