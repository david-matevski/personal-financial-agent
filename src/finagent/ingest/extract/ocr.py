"""OCR extraction backend (Tesseract via pytesseract + pypdfium2).

Used only for pages whose text layer is missing or unusably short (scanned
statements or image-only pages). Optional dependencies are imported lazily
so the rest of the app works without the ``ocr`` extra installed. OCR is
always requested one page at a time (see ``extract/fallback.py``), so a
missing text layer on one page never requires rendering the whole document.
"""

import logging
from typing import Any

from finagent.core.errors import ExtractionError

logger = logging.getLogger(__name__)

_RENDER_DPI = 300
_RENDER_SCALE = _RENDER_DPI / 72  # pypdfium2 render() scale is relative to 72 dpi


class TesseractOcrExtractor:
    """Renders one page to an image and runs Tesseract OCR over it."""

    def ocr_page(self, pdf_bytes: bytes, page_index: int) -> str:
        """Return the OCR'd text of the page at ``page_index`` (0-based)."""
        pdfium, pytesseract = _import_ocr_deps()
        try:
            pdf = pdfium.PdfDocument(pdf_bytes)
        except Exception as exc:
            raise ExtractionError(f"Failed to open PDF for OCR: {exc}") from exc

        try:
            page = pdf[page_index]
            try:
                bitmap = page.render(scale=_RENDER_SCALE)
                image = bitmap.to_pil()
                text = pytesseract.image_to_string(image)
            finally:
                page.close()
        except Exception as exc:
            raise ExtractionError(f"OCR failed for page {page_index + 1}: {exc}") from exc
        finally:
            pdf.close()
        return str(text)


def _import_ocr_deps() -> tuple[Any, Any]:  # Any: optional deps typed only via stubs we don't ship
    try:
        import pypdfium2
    except ImportError as exc:
        raise ExtractionError(
            "OCR requires the 'ocr' extra: install with `pip install -e '.[ocr]'` "
            "(needs pypdfium2)."
        ) from exc
    try:
        import pytesseract
    except ImportError as exc:
        raise ExtractionError(
            "OCR requires the 'ocr' extra: install with `pip install -e '.[ocr]'` "
            "(needs pytesseract, and the Tesseract binary on PATH)."
        ) from exc
    return pypdfium2, pytesseract
