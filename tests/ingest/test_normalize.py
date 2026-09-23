"""Tests for finagent.ingest.normalize: StatementExtraction -> ParsedStatement."""

from datetime import date
from decimal import Decimal

import pytest

from finagent.core.errors import ParseError
from finagent.domain.models import AccountType
from finagent.ingest.extract.schema import StatementExtraction
from finagent.ingest.normalize import normalize, parse_amount


def _extraction(**overrides: object) -> StatementExtraction:
    defaults: dict[str, object] = {
        "issuer": "TD",
        "account_name": "TD Rewards Visa",
        "account_last4": "1234",
        "account_type": "CREDIT",
        "currency": "CAD",
        "period_start": "2026-01-01",
        "period_end": "2026-01-31",
        "opening_balance": "100.00",
        "closing_balance": "150.00",
        "total_money_out": None,
        "total_money_in": None,
        "transactions": [
            {
                "transaction_date": "2026-01-05",
                "posted_date": "2026-01-06",
                "description": "Fictional Coffee Co",
                "amount": "5.00",
                "direction": "OUT",
                "running_balance": None,
            }
        ],
    }
    defaults.update(overrides)
    return StatementExtraction.model_validate(defaults)


def test_parse_amount_strips_dollar_sign_and_commas() -> None:
    assert parse_amount("$1,234.56") == Decimal("1234.56")


def test_parse_amount_accepts_plain_decimal() -> None:
    assert parse_amount("12.34") == Decimal("12.34")


def test_parse_amount_rejects_space_separated_junk() -> None:
    with pytest.raises(ParseError):
        parse_amount("1 234,56")


def test_parse_amount_rejects_non_numeric_text() -> None:
    with pytest.raises(ParseError):
        parse_amount("not a number")


def test_normalize_out_direction_is_positive() -> None:
    extraction = _extraction(
        transactions=[
            {
                "posted_date": "2026-01-06",
                "description": "Fictional Coffee Co",
                "amount": "5.00",
                "direction": "OUT",
            }
        ]
    )
    statement = normalize(extraction)
    assert statement.transactions[0].amount == Decimal("5.00")


def test_normalize_in_direction_is_negative() -> None:
    extraction = _extraction(
        transactions=[
            {
                "posted_date": "2026-01-06",
                "description": "Payment received",
                "amount": "5.00",
                "direction": "IN",
            }
        ]
    )
    statement = normalize(extraction)
    assert statement.transactions[0].amount == Decimal("-5.00")


def test_normalize_builds_account_label_from_issuer_and_last4() -> None:
    statement = normalize(_extraction(issuer="td", account_last4="5678"))
    assert statement.account_label == "TD ****5678"


def test_normalize_strips_non_digits_from_last4() -> None:
    statement = normalize(_extraction(account_last4="X1234"))
    assert statement.account_label == "TD ****1234"


def test_normalize_sets_account_type() -> None:
    statement = normalize(_extraction(account_type="DEBIT"))
    assert statement.account_type is AccountType.DEBIT


def test_normalize_parses_period_dates() -> None:
    statement = normalize(_extraction(period_start="2026-01-01", period_end="2026-01-31"))
    assert statement.period_start == date(2026, 1, 1)
    assert statement.period_end == date(2026, 1, 31)


def test_normalize_allows_missing_period() -> None:
    statement = normalize(_extraction(period_start=None, period_end=None))
    assert statement.period_start is None
    assert statement.period_end is None


def test_normalize_rejects_unparseable_amount() -> None:
    extraction = _extraction(
        transactions=[
            {
                "posted_date": "2026-01-06",
                "description": "Fictional Coffee Co",
                "amount": "garbage",
                "direction": "OUT",
            }
        ]
    )
    with pytest.raises(ParseError):
        normalize(extraction)


def test_normalize_assigns_row_sequence_to_duplicate_lines() -> None:
    tx = {
        "posted_date": "2026-01-06",
        "description": "Fictional Coffee Co",
        "amount": "5.00",
        "direction": "OUT",
    }
    extraction = _extraction(transactions=[tx, dict(tx)])
    statement = normalize(extraction)
    assert [t.row_sequence for t in statement.transactions] == [0, 1]
