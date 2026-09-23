"""Tests for text-layer PDF extraction (fpdf2-built synthetic PDFs)."""

from fpdf import FPDF

from finagent.ingest.extract.pdf_text import PdfTextExtractor


def _build_pdf(lines_per_page: list[list[str]]) -> bytes:
    pdf = FPDF()
    for lines in lines_per_page:
        pdf.add_page()
        pdf.set_font("Helvetica", size=12)
        for line in lines:
            pdf.cell(0, 10, text=line, new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


def test_extracts_text_per_page() -> None:
    pdf_bytes = _build_pdf(
        [
            ["Fictional Bank Statement", "Account holder: Jane Sample"],
            ["Transactions", "01/02 Made Up Cafe 12.34"],
        ]
    )

    pages = PdfTextExtractor().extract(pdf_bytes)

    assert len(pages) == 2
    assert "Fictional Bank Statement" in pages[0]
    assert "Account holder: Jane Sample" in pages[0]
    assert "Made Up Cafe" in pages[1]


def test_blank_page_yields_empty_string() -> None:
    pdf_bytes = _build_pdf([[]])

    pages = PdfTextExtractor().extract(pdf_bytes)

    assert len(pages) == 1
    assert pages[0].strip() == ""
