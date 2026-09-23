"""Tests for the TD Visa credit card PDF parser (synthetic fixture only)."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from finagent.core.errors import ParseError
from finagent.domain.models import AccountType, Issuer
from finagent.ingest.document import DocumentKind, SourceDocument
from finagent.ingest.parsers.td import TdCreditPdfParser

FIXTURE_PATH = Path(__file__).parent.parent.parent / "fixtures" / "td" / "visa_statement.txt"


def _load_pages(path: Path = FIXTURE_PATH) -> tuple[str, ...]:
    return tuple(path.read_text(encoding="utf-8").split("\f"))


def _make_doc(pages: tuple[str, ...]) -> SourceDocument:
    return SourceDocument(filename="visa_statement.pdf", kind=DocumentKind.TEXT, pages=pages)


@pytest.fixture
def statement_doc() -> SourceDocument:
    return _make_doc(_load_pages())


@pytest.fixture
def parser() -> TdCreditPdfParser:
    return TdCreditPdfParser()


def test_can_parse_true_for_td_statement(
    parser: TdCreditPdfParser, statement_doc: SourceDocument
) -> None:
    assert parser.can_parse(statement_doc) is True


def test_can_parse_false_for_non_td_text_doc(parser: TdCreditPdfParser) -> None:
    doc = SourceDocument(
        filename="other.pdf",
        kind=DocumentKind.TEXT,
        pages=("Some Other Bank\nStatement of Account\nTotal Due $12.34",),
    )
    assert parser.can_parse(doc) is False


def test_can_parse_false_for_table_doc(parser: TdCreditPdfParser) -> None:
    doc = SourceDocument(
        filename="other.csv",
        kind=DocumentKind.TABLE,
        rows=(("Date", "Description", "Amount"), ("2026-01-01", "TD Visa", "$1.00")),
    )
    assert parser.can_parse(doc) is False


def test_happy_path_parses_transactions(
    parser: TdCreditPdfParser, statement_doc: SourceDocument
) -> None:
    result = parser.parse(statement_doc)

    assert result.issuer is Issuer.TD
    assert result.account_label == "TD Cash Back Visa Infinite ****0000"
    assert result.period_start == date(2025, 12, 28)
    assert result.period_end == date(2026, 2, 10)

    # 6 transactions on page 1 + 2 identical charges on page 2.
    assert len(result.transactions) == 8

    first = result.transactions[0]
    assert first.description == "GREENLEAF MARKET TORONTO"
    assert first.amount == Decimal("42.15")
    assert first.transaction_date == date(2025, 12, 29)
    assert first.posted_date == date(2025, 12, 31)
    assert first.account_type is AccountType.CREDIT
    assert first.issuer is Issuer.TD

    last = result.transactions[-1]
    assert last.description == "PARKSIDE COFFEE TORONTO"
    assert last.amount == Decimal("4.50")
    assert last.transaction_date == date(2026, 2, 1)
    assert last.posted_date == date(2026, 2, 3)

    payment = next(tx for tx in result.transactions if tx.description.startswith("ONLINE PAYMENT"))
    assert payment.amount == Decimal("-150.00")


def test_fx_purchase_ignores_foreign_currency_and_rate_lines(
    parser: TdCreditPdfParser, statement_doc: SourceDocument
) -> None:
    result = parser.parse(statement_doc)
    fx_tx = next(tx for tx in result.transactions if tx.description == "GLOBALGADGET SHOP SG")
    assert fx_tx.amount == Decimal("88.10")


def test_duplicate_same_day_charges_get_distinct_row_sequences(
    parser: TdCreditPdfParser, statement_doc: SourceDocument
) -> None:
    result = parser.parse(statement_doc)
    duplicates = [tx for tx in result.transactions if tx.description == "PARKSIDE COFFEE TORONTO"]
    assert len(duplicates) == 2
    assert {tx.row_sequence for tx in duplicates} == {0, 1}


def test_transaction_date_before_posting_year_crossover(
    parser: TdCreditPdfParser, statement_doc: SourceDocument
) -> None:
    result = parser.parse(statement_doc)
    crossing_tx = next(
        tx for tx in result.transactions if tx.description == "CLOUDNINE CAFE VANCOUVER"
    )
    assert crossing_tx.transaction_date == date(2025, 12, 30)
    assert crossing_tx.posted_date == date(2026, 1, 2)


def test_transaction_date_before_period_start_same_year(parser: TdCreditPdfParser) -> None:
    """A December transaction line under a non-crossing Jan-Feb period.

    Regression for a bug where the year was inferred from period_start,
    which put such a line's transaction_date a full year in the future
    (e.g. 2027-12-30 instead of 2026-12-30) since no statement line is ever
    dated after its own period end.
    """
    page = "\n".join(
        [
            "TD Value Visa*",
            "5500 11XX XXXX 1234",
            "STATEMENT PERIOD: January 12, 2027 to February 11, 2027",
            "TRANSACTION POSTING",
            "DATE DATE ACTIVITY DESCRIPTION AMOUNT($)",
            "PREVIOUS STATEMENT BALANCE $0.00",
            "DEC 30 JAN 13 LATE DECEMBER PURCHASE $19.99",
            "NEW BALANCE $19.99",
        ]
    )
    doc = _make_doc((page,))

    result = parser.parse(doc)

    assert len(result.transactions) == 1
    tx = result.transactions[0]
    assert tx.transaction_date == date(2026, 12, 30)
    assert tx.posted_date == date(2027, 1, 13)


def test_reconciliation_failure_raises_parse_error(parser: TdCreditPdfParser) -> None:
    pages = list(_load_pages())
    pages[1] = pages[1].replace("TOTAL NEW BALANCE $490.48", "TOTAL NEW BALANCE $999.99")
    doc = _make_doc(tuple(pages))

    with pytest.raises(ParseError):
        parser.parse(doc)
