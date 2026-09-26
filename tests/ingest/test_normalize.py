"""Tests for finagent.ingest.normalize: StatementExtraction -> ParsedStatement."""

from datetime import date
from decimal import Decimal

import pytest

from finagent.core.errors import ParseError
from finagent.domain.models import AccountType
from finagent.ingest.extract.schema import StatementExtraction
from finagent.ingest.normalize import (
    interpret_balance,
    interpret_total,
    normalize,
    normalize_issuer,
    normalize_last4,
)


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
    assert statement.notes == ()


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


def test_normalize_printed_credit_marker_wins_over_model_direction() -> None:
    """A trailing CR marker overrides a model that mislabels the direction OUT."""
    extraction = _extraction(
        transactions=[
            {
                "posted_date": "2026-01-06",
                "description": "Payment received",
                "amount": "270.46CR",
                "direction": "OUT",  # the model got it wrong
            }
        ]
    )
    statement = normalize(extraction)
    assert statement.transactions[0].amount == Decimal("-270.46")
    assert len(statement.notes) == 1
    assert "direction corrected" in statement.notes[0]
    assert "1 transaction" in statement.notes[0]


@pytest.mark.parametrize(
    ("amount", "model_direction", "expected"),
    [
        ("(12.00)", "OUT", Decimal("-12.00")),  # parentheses -> money in
        ("-12.00", "OUT", Decimal("-12.00")),  # minus sign -> money in
        ("12.00CR", "OUT", Decimal("-12.00")),  # CR text -> money in
        ("12.00DR", "IN", Decimal("12.00")),  # DR text -> money out
    ],
)
def test_normalize_printed_sign_or_marker_wins_over_model_direction(
    amount: str, model_direction: str, expected: Decimal
) -> None:
    extraction = _extraction(
        transactions=[
            {
                "posted_date": "2026-01-06",
                "description": "Fictional Coffee Co",
                "amount": amount,
                "direction": model_direction,
            }
        ]
    )
    statement = normalize(extraction)
    assert statement.transactions[0].amount == expected


def test_normalize_printed_marker_agreeing_with_direction_adds_no_note() -> None:
    extraction = _extraction(
        transactions=[
            {
                "posted_date": "2026-01-06",
                "description": "Payment received",
                "amount": "270.46CR",
                "direction": "IN",  # model already agrees with the CR marker
            }
        ]
    )
    statement = normalize(extraction)
    assert statement.transactions[0].amount == Decimal("-270.46")
    assert statement.notes == ()


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


@pytest.mark.parametrize(
    ("issuer", "last4"),
    [("TD", "1234"), (" td ", "1234"), ("Td", "**** 1234"), ("TD", "XXXX-XXXX-1234")],
)
def test_issuer_and_last4_variants_normalize_to_one_identity(issuer: str, last4: str) -> None:
    assert normalize_issuer(issuer) == "TD"
    assert normalize_last4(last4) == "1234"


# --- interpret_balance / interpret_total: AGENTS.md task spec §2 sign rules ---


def test_interpret_balance_none_passes_through() -> None:
    assert interpret_balance(None, AccountType.CREDIT) is None


def test_interpret_balance_credit_account_credit_marker_is_negative() -> None:
    assert interpret_balance("50.00CR", AccountType.CREDIT) == Decimal("-50.00")


def test_interpret_balance_credit_account_unmarked_is_positive() -> None:
    assert interpret_balance("150.00", AccountType.CREDIT) == Decimal("150.00")


def test_interpret_balance_credit_account_debit_marker_is_positive() -> None:
    assert interpret_balance("150.00DR", AccountType.CREDIT) == Decimal("150.00")


def test_interpret_balance_credit_account_minus_sign_is_negative() -> None:
    assert interpret_balance("-50.00", AccountType.CREDIT) == Decimal("-50.00")


def test_interpret_balance_debit_account_unmarked_is_positive() -> None:
    assert interpret_balance("100.00", AccountType.DEBIT) == Decimal("100.00")


def test_interpret_balance_debit_account_credit_marker_is_positive_in_credit() -> None:
    """A DEBIT (bank) account routinely prints "1,234.56 CR" to confirm a
    perfectly normal, positive balance -- CR text must not flip the sign.
    """
    assert interpret_balance("1,234.56CR", AccountType.DEBIT) == Decimal("1234.56")


def test_interpret_balance_debit_account_debit_marker_is_negative_overdraft() -> None:
    assert interpret_balance("50.00DR", AccountType.DEBIT) == Decimal("-50.00")


def test_interpret_balance_debit_account_minus_sign_is_negative_overdraft() -> None:
    assert interpret_balance("-50.00", AccountType.DEBIT) == Decimal("-50.00")


def test_interpret_total_is_always_a_magnitude() -> None:
    assert interpret_total("-5.00") == Decimal("5.00")
    assert interpret_total("5.00CR") == Decimal("5.00")
    assert interpret_total(None) is None


# --- Behaviour change: "1 234,56" is now a valid European-format amount ---


def test_space_grouped_european_amount_now_parses() -> None:
    """Previously rejected by the old parse_amount (any internal space was
    treated as junk); interpret_amount now recognizes space as a thousands
    separator, so this is an intentional behaviour change.
    """
    extraction = _extraction(
        transactions=[
            {
                "posted_date": "2026-01-06",
                "description": "Fictional Coffee Co",
                "amount": "1 234,56",
                "direction": "OUT",
            }
        ]
    )
    statement = normalize(extraction)
    assert statement.transactions[0].amount == Decimal("1234.56")
