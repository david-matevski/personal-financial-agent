"""Tests for load_document: dispatch on content sniffing + per-format extraction."""

import io
from pathlib import Path

import openpyxl
import pytest

from finagent.core.errors import UnsupportedStatementError
from finagent.ingest.document import DocumentKind
from finagent.ingest.loaders import load_document

FIXTURES = Path(__file__).parent.parent / "fixtures" / "loaders"

# Minimal-but-valid signatures for each format; loaders only sniff the
# magic bytes, so the rest of the content can be arbitrary synthetic bytes.
_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
_JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 16
_GIF_BYTES = b"GIF89a" + b"\x00" * 16
_WEBP_BYTES = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 8
_PDF_BYTES = b"%PDF-1.7\n" + b"%%fake synthetic pdf body for a loader test\n" * 3


def test_csv_loads_as_table() -> None:
    csv_bytes = "Date,Merchant,Amount\n2026-01-15,Fictional Coffee Co,12.00\n".encode("utf-8-sig")

    doc = load_document("sample.csv", csv_bytes)

    assert doc.kind is DocumentKind.TABLE
    assert doc.rows == (
        ("Date", "Merchant", "Amount"),
        ("2026-01-15", "Fictional Coffee Co", "12.00"),
    )


def test_xlsx_loads_as_table_with_stringified_cells() -> None:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.append(["Date", "Merchant", "Amount"])
    sheet.append(["2026-02-01", "Fictional Widget Shop", 19.0])
    sheet.append(["2026-02-02", "Sample Grocery", 8.75])
    buffer = io.BytesIO()
    workbook.save(buffer)

    doc = load_document("sample.xlsx", buffer.getvalue())

    assert doc.kind is DocumentKind.TABLE
    assert doc.rows[0] == ("Date", "Merchant", "Amount")
    assert doc.rows[1] == ("2026-02-01", "Fictional Widget Shop", "19")
    assert doc.rows[2] == ("2026-02-02", "Sample Grocery", "8.75")


def test_legacy_xls_fixture_loads_as_table() -> None:
    data = (FIXTURES / "sample.xls").read_bytes()

    doc = load_document("sample.xls", data)

    assert doc.kind is DocumentKind.TABLE
    assert len(doc.rows) == 3
    header, first, second = doc.rows
    assert header == ("Date", "Merchant", "Amount")
    # date-typed cell -> ISO date; whole-number float -> no trailing .0
    assert first[0] == "2026-01-15"
    assert first[2] == "12"
    assert second[2] == "45.5"


def test_pdf_loads_with_raw_bytes_and_media_type() -> None:
    doc = load_document("statement.pdf", _PDF_BYTES)

    assert doc.kind is DocumentKind.PDF
    assert doc.data == _PDF_BYTES
    assert doc.media_type == "application/pdf"
    assert doc.rows == ()


@pytest.mark.parametrize(
    ("filename", "data", "media_type"),
    [
        ("scan.png", _PNG_BYTES, "image/png"),
        ("scan.jpg", _JPEG_BYTES, "image/jpeg"),
        ("scan.gif", _GIF_BYTES, "image/gif"),
        ("scan.webp", _WEBP_BYTES, "image/webp"),
    ],
)
def test_image_formats_load_as_image_with_media_type(
    filename: str, data: bytes, media_type: str
) -> None:
    doc = load_document(filename, data)

    assert doc.kind is DocumentKind.IMAGE
    assert doc.data == data
    assert doc.media_type == media_type


def test_unknown_bytes_raise_unsupported_statement_error() -> None:
    with pytest.raises(UnsupportedStatementError):
        load_document("mystery.bin", b"\x00\x01\x02\xff\xfe\xfd not text and not a known format")


def test_empty_bytes_raise_unsupported_statement_error() -> None:
    with pytest.raises(UnsupportedStatementError):
        load_document("empty.csv", b"")
