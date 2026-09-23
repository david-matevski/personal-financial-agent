"""Text-layer PDF extraction via pdfplumber.

This is the first extraction pass for every PDF: cheap and accurate for
statements that were generated digitally rather than scanned. Pages with
no usable text layer fall back to OCR (see ``extract/fallback.py``).
"""

import io

import pdfplumber

from finagent.core.errors import ExtractionError

# The default pdfplumber word-join tolerance merges adjacent words on some
# statement layouts (verified against TD statements). A tighter x_tolerance
# keeps distinct columns/words from being glued together.
_X_TOLERANCE = 1


class PdfTextExtractor:
    """Extracts per-page text using the PDF's embedded text layer."""

    def extract(self, pdf_bytes: bytes) -> list[str]:
        """Return one string of extracted text per page, in page order."""
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                return [page.extract_text(x_tolerance=_X_TOLERANCE) or "" for page in pdf.pages]
        except Exception as exc:  # pdfplumber/pdfminer raise assorted errors on bad input
            raise ExtractionError(f"Failed to extract PDF text layer: {exc}") from exc
