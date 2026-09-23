"""Tests for the per-page OCR fallback decision logic.

The OCR backend itself is faked here (no real Tesseract needed); a
separate real-Tesseract test lives in test_ocr.py, skipped when the
tesseract binary isn't on PATH.
"""

import pytest

from finagent.core.errors import ExtractionError
from finagent.ingest.extract.fallback import FallbackTextExtractor


class _FakeTextExtractor:
    def __init__(self, pages: list[str]) -> None:
        self._pages = pages

    def extract(self, pdf_bytes: bytes) -> list[str]:
        return self._pages


class _FakePageOcr:
    """Records which page indices it was asked to OCR."""

    def __init__(self, pages_by_index: dict[int, str]) -> None:
        self._pages_by_index = pages_by_index
        self.requested_indices: list[int] = []

    def ocr_page(self, pdf_bytes: bytes, page_index: int) -> str:
        self.requested_indices.append(page_index)
        return self._pages_by_index[page_index]


class _UnavailablePageOcr:
    """Simulates OCR deps/binary being missing: every call fails."""

    def __init__(self) -> None:
        self.requested_indices: list[int] = []

    def ocr_page(self, pdf_bytes: bytes, page_index: int) -> str:
        self.requested_indices.append(page_index)
        raise ExtractionError("OCR requires the 'ocr' extra")


def test_skips_ocr_when_all_pages_have_text() -> None:
    text_extractor = _FakeTextExtractor(["Plenty of real text content here, page one."])
    page_ocr = _FakePageOcr({})

    pages = FallbackTextExtractor(text_extractor, page_ocr).extract(b"fake-pdf-bytes")

    assert pages == ["Plenty of real text content here, page one."]
    assert page_ocr.requested_indices == []


def test_ocrs_only_sparse_pages() -> None:
    text_extractor = _FakeTextExtractor(
        [
            "Plenty of real text content on this page.",
            "   ",  # blank / image-only page
            "Also plenty of real text content here.",
        ]
    )
    page_ocr = _FakePageOcr({1: "page2 ocr (from image)"})

    pages = FallbackTextExtractor(text_extractor, page_ocr).extract(b"fake-pdf-bytes")

    assert pages == [
        "Plenty of real text content on this page.",
        "page2 ocr (from image)",
        "Also plenty of real text content here.",
    ]
    # only the sparse page (index 1) was sent to OCR -- not pages 0 or 2
    assert page_ocr.requested_indices == [1]


def test_short_text_under_threshold_triggers_ocr() -> None:
    text_extractor = _FakeTextExtractor(["short"])
    page_ocr = _FakePageOcr({0: "ocr result"})

    pages = FallbackTextExtractor(text_extractor, page_ocr).extract(b"fake-pdf-bytes")

    assert pages == ["ocr result"]
    assert page_ocr.requested_indices == [0]


def test_unavailable_ocr_with_partially_sparse_doc_degrades_gracefully() -> None:
    text_extractor = _FakeTextExtractor(
        [
            "Plenty of real text content on this page.",
            "   ",  # sparse: back page holding only a barcode
        ]
    )
    page_ocr = _UnavailablePageOcr()

    pages = FallbackTextExtractor(text_extractor, page_ocr).extract(b"fake-pdf-bytes")

    # OCR failed, but only one page was sparse -- the sparse text-layer
    # output is kept as-is instead of raising.
    assert pages == ["Plenty of real text content on this page.", "   "]
    assert page_ocr.requested_indices == [1]


def test_unavailable_ocr_with_fully_sparse_doc_raises() -> None:
    text_extractor = _FakeTextExtractor(["", "   "])
    page_ocr = _UnavailablePageOcr()

    with pytest.raises(ExtractionError):
        FallbackTextExtractor(text_extractor, page_ocr).extract(b"fake-pdf-bytes")
