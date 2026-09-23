"""Turns raw uploaded bytes into a format-neutral ``SourceDocument``.

Dispatch is by content sniffing (magic bytes), with the filename extension
used only as a hint when the bytes don't carry a recognizable signature
(plain-text CSV has none). Extraction never sees raw bytes or file formats
directly -- only the ``SourceDocument`` this module produces.
"""

import csv
import datetime
import io
from pathlib import Path

import openpyxl
import xlrd

from finagent.core.errors import ExtractionError, UnsupportedStatementError
from finagent.ingest.document import DocumentKind, SourceDocument

_PDF_MAGIC = b"%PDF"
_OLE2_MAGIC = (
    b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # legacy .xls (and other MS Office binary formats)
)
_ZIP_MAGIC = b"PK\x03\x04"  # .xlsx (and other Office Open XML formats)
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"
_GIF_MAGIC_PREFIXES = (b"GIF87a", b"GIF89a")
_RIFF_MAGIC = b"RIFF"
_WEBP_MAGIC = b"WEBP"


def load_document(filename: str, data: bytes) -> SourceDocument:
    """Detect the statement format and load it into a ``SourceDocument``.

    Raises ``UnsupportedStatementError`` if the bytes don't match any
    supported format, ``ExtractionError`` if the format is recognized but
    loading fails (corrupt/unreadable workbook, malformed CSV, ...).
    """
    if not data:
        raise UnsupportedStatementError(f"{filename}: empty file")

    if data.startswith(_PDF_MAGIC):
        return SourceDocument(
            filename=filename, kind=DocumentKind.PDF, data=data, media_type="application/pdf"
        )
    if data.startswith(_OLE2_MAGIC):
        return _load_xls(filename, data)
    if data.startswith(_ZIP_MAGIC):
        return _load_xlsx(filename, data)

    image_media_type = _sniff_image_media_type(data)
    if image_media_type is not None:
        return SourceDocument(
            filename=filename, kind=DocumentKind.IMAGE, data=data, media_type=image_media_type
        )

    # No recognizable binary signature: fall back to CSV, using the
    # extension as a hint for the error message only.
    ext = Path(filename).suffix.lower()
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise UnsupportedStatementError(
            f"{filename}: unrecognized statement format (ext={ext or 'none'})"
        ) from exc
    return _load_csv_text(filename, text)


def _sniff_image_media_type(data: bytes) -> str | None:
    """Return the media type for a recognized image signature, else None."""
    if data.startswith(_PNG_MAGIC):
        return "image/png"
    if data.startswith(_JPEG_MAGIC):
        return "image/jpeg"
    if data.startswith(_GIF_MAGIC_PREFIXES):
        return "image/gif"
    if data.startswith(_RIFF_MAGIC) and data[8:12] == _WEBP_MAGIC:
        return "image/webp"
    return None


def _load_xls(filename: str, data: bytes) -> SourceDocument:
    try:
        book = xlrd.open_workbook(file_contents=data)
    except Exception as exc:
        raise ExtractionError(f"Failed to open legacy XLS {filename}: {exc}") from exc

    sheet = book.sheet_by_index(0)
    rows = tuple(
        tuple(
            _stringify_xls_cell(sheet.cell(row_index, col_index), book.datemode)
            for col_index in range(sheet.ncols)
        )
        for row_index in range(sheet.nrows)
    )
    return SourceDocument(filename=filename, kind=DocumentKind.TABLE, rows=rows)


def _load_xlsx(filename: str, data: bytes) -> SourceDocument:
    try:
        workbook = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:
        raise ExtractionError(f"Failed to open XLSX {filename}: {exc}") from exc

    try:
        sheet = workbook.worksheets[0]
        rows = tuple(
            tuple(_stringify_cell(value) for value in row)
            for row in sheet.iter_rows(values_only=True)
        )
    except Exception as exc:
        raise ExtractionError(f"Failed to read XLSX {filename}: {exc}") from exc
    finally:
        workbook.close()
    return SourceDocument(filename=filename, kind=DocumentKind.TABLE, rows=rows)


def _load_csv_text(filename: str, text: str) -> SourceDocument:
    try:
        rows = tuple(tuple(cell.strip() for cell in row) for row in csv.reader(io.StringIO(text)))
    except csv.Error as exc:
        raise ExtractionError(f"Failed to parse CSV {filename}: {exc}") from exc
    if not rows:
        raise UnsupportedStatementError(f"{filename}: no rows found")
    return SourceDocument(filename=filename, kind=DocumentKind.TABLE, rows=rows)


def _stringify_cell(value: object) -> str:
    """Stringify an openpyxl cell value the way extraction expects to see it."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, datetime.date):  # datetime.datetime is a subclass of date
        return value.strftime("%Y-%m-%d")
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return _stringify_number(value)
    return str(value).strip()


def _stringify_xls_cell(cell: xlrd.sheet.Cell, datemode: int) -> str:
    """Stringify an xlrd cell value, handling xlrd's serial date encoding."""
    if cell.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
        return ""
    if cell.ctype == xlrd.XL_CELL_DATE:
        dt = xlrd.xldate_as_datetime(cell.value, datemode)
        return str(dt.strftime("%Y-%m-%d"))
    if cell.ctype == xlrd.XL_CELL_NUMBER:
        return _stringify_number(cell.value)
    if cell.ctype == xlrd.XL_CELL_BOOLEAN:
        return str(bool(cell.value))
    return str(cell.value).strip()


def _stringify_number(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return str(value)
