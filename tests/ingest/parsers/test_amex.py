"""Tests for finagent.ingest.parsers.amex.

Row layout is invented (fake cardholder, fake account, fake merchants) but
mimics the real Amex "Transaction Details" export structure documented in
AGENTS.md §6: it must never be built from the real sample statement.
"""

from datetime import date
from decimal import Decimal

import pytest

from finagent.core.errors import ParseError
from finagent.ingest.document import DocumentKind, SourceDocument
from finagent.ingest.parsers.amex import AmexExportParser

Row = tuple[str, ...]

_PRODUCT = "American Express® Sample Rewards Card"
_CARDHOLDER = "JANE Q SAMPLE"
_ACCOUNT = "Account Number: XXX-00000"


def _header_rows(
    *,
    product: str = _PRODUCT,
    cardholder: str = _CARDHOLDER,
    account: str = _ACCOUNT,
    period: str = "14 Mar. 2026 - 04 Apr. 2026",
) -> list[Row]:
    return [
        ("", "Transaction Details: ", product, ""),
        ("", cardholder, period, ""),
        ("", account, "", ""),
        ("", "", "", ""),
    ]


def _summary_rows(
    *,
    last_billed: str = "$500.00",
    charges: str = "$137.34",
    payments: str = "$250.00",
    summary: str = "$387.34",
) -> list[Row]:
    return [
        ("Summary", "", "", "Total"),
        ("Last billed statement", "", "", last_billed),
        ("Charges & Adjustments", "", "", charges),
        ("Payments & Credits", "", "", payments),
        ("Summary for this billed period:", "", "", summary),
        ("", "", "", ""),
    ]


_TXN_HEADER: Row = ("Date", "Description", "", "Amount")

# Newest-first, as Amex exports them. Includes: a payment credit, two
# identical same-day charges, a "Sept." date, and a "May" date without a
# trailing period on the month.
_DEFAULT_TXN_ROWS: list[Row] = [
    ("04 Apr. 2026", "PAYMENT RECEIVED - THANK YOU", "", "-$250.00"),
    ("02 Apr. 2026", "SAMPLE COFFEE HOUSE     Springfield", "", "$12.34"),
    ("02 Apr. 2026", "SAMPLE COFFEE HOUSE     Springfield", "", "$12.34"),
    ("20 Sept. 2025", "SAMPLE BOOKSTORE        Shelbyville", "", "$45.00"),
    ("05 May 2025", "SAMPLE HARDWARE STORE   Capital City", "", "$67.66"),
]


def _build_rows(
    *,
    txn_rows: list[Row] | None = None,
    extra_row_before_header: Row | None = None,
    trailing_rows: list[Row] | None = None,
    **summary_overrides: str,
) -> tuple[Row, ...]:
    rows = [*_header_rows(), *_summary_rows(**summary_overrides)]
    if extra_row_before_header is not None:
        rows.append(extra_row_before_header)
    rows.append(_TXN_HEADER)
    rows.extend(_DEFAULT_TXN_ROWS if txn_rows is None else txn_rows)
    if trailing_rows:
        rows.append(("", "", "", ""))
        rows.extend(trailing_rows)
    return tuple(rows)


def _doc(rows: tuple[Row, ...]) -> SourceDocument:
    return SourceDocument(filename="amex.xls", kind=DocumentKind.TABLE, rows=rows)


def test_can_parse_true_for_amex_table() -> None:
    parser = AmexExportParser()
    assert parser.can_parse(_doc(_build_rows())) is True


def test_can_parse_false_for_text_document() -> None:
    parser = AmexExportParser()
    doc = SourceDocument(filename="statement.pdf", kind=DocumentKind.TEXT, pages=("hello",))
    assert parser.can_parse(doc) is False


def test_can_parse_false_for_unrelated_table() -> None:
    parser = AmexExportParser()
    rows: tuple[Row, ...] = (
        ("Date", "Description", "Amount", ""),
        ("2026-04-01", "SOME MERCHANT", "12.00", ""),
    )
    assert parser.can_parse(_doc(rows)) is False


def test_can_parse_does_not_raise_on_empty_document() -> None:
    parser = AmexExportParser()
    assert parser.can_parse(_doc(())) is False


def test_happy_path_parses_and_reconciles() -> None:
    parser = AmexExportParser()
    result = parser.parse(_doc(_build_rows()))

    assert result.account_label == "American Express Sample Rewards Card ****0000"
    assert result.period_start == date(2026, 3, 14)
    assert result.period_end == date(2026, 4, 4)
    assert len(result.transactions) == 5

    # Output is chronological (oldest first).
    dates = [tx.posted_date for tx in result.transactions]
    assert dates == sorted(dates)
    assert dates[0] == date(2025, 5, 5)
    assert dates[-1] == date(2026, 4, 4)

    for tx in result.transactions:
        assert tx.account_type.value == "CREDIT"
        assert tx.transaction_date is None
        assert tx.amount == tx.amount.quantize(Decimal("0.01"))

    payment = next(tx for tx in result.transactions if tx.amount < 0)
    assert payment.amount == Decimal("-250.00")
    assert payment.description == "PAYMENT RECEIVED - THANK YOU"


def test_duplicate_same_day_charges_get_distinct_row_sequences() -> None:
    parser = AmexExportParser()
    result = parser.parse(_doc(_build_rows()))
    coffees = [tx for tx in result.transactions if "COFFEE" in tx.description]
    assert len(coffees) == 2
    assert {tx.row_sequence for tx in coffees} == {0, 1}


def test_reconciliation_failure_sum_mismatch_raises_parse_error() -> None:
    parser = AmexExportParser()
    rows = _build_rows(charges="$999.99")
    with pytest.raises(ParseError):
        parser.parse(_doc(rows))


def test_reconciliation_failure_summary_mismatch_raises_parse_error() -> None:
    parser = AmexExportParser()
    rows = _build_rows(summary="$1.23")
    with pytest.raises(ParseError):
        parser.parse(_doc(rows))


def test_header_row_located_after_extra_inserted_row() -> None:
    parser = AmexExportParser()
    rows = _build_rows(extra_row_before_header=("Rewards Balance", "", "", "12,345"))
    result = parser.parse(_doc(rows))
    assert len(result.transactions) == 5


def test_stops_at_first_blank_row_after_transactions() -> None:
    parser = AmexExportParser()
    rows = _build_rows(trailing_rows=[("stray", "footer text", "", "")])
    result = parser.parse(_doc(rows))
    assert len(result.transactions) == 5


def test_date_variants_parse_correctly() -> None:
    parser = AmexExportParser()
    result = parser.parse(_doc(_build_rows()))
    sept_txn = next(tx for tx in result.transactions if tx.description.startswith("SAMPLE BOOK"))
    may_txn = next(tx for tx in result.transactions if tx.description.startswith("SAMPLE HARD"))
    assert sept_txn.posted_date == date(2025, 9, 20)
    assert may_txn.posted_date == date(2025, 5, 5)
