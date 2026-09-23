"""Tests for finagent.domain.models."""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from finagent.domain.models import AccountType, ParsedStatement, Transaction


def _make_transaction(**overrides: object) -> Transaction:
    defaults: dict[str, object] = {
        "issuer": "TD",
        "account_type": AccountType.DEBIT,
        "account_label": "Chequing 1234",
        "posted_date": date(2024, 1, 15),
        "transaction_date": date(2024, 1, 14),
        "description": "COFFEE SHOP",
        "amount": Decimal("4.50"),
        "running_balance": Decimal("1000.00"),
    }
    defaults.update(overrides)
    return Transaction.model_validate(defaults)


def test_transaction_accepts_valid_decimal_amount() -> None:
    tx = _make_transaction(amount=Decimal("12.34"))
    assert tx.amount == Decimal("12.34")


def test_transaction_rejects_float_amount() -> None:
    with pytest.raises(ValidationError):
        _make_transaction(amount=4.50)


def test_transaction_rejects_float_running_balance() -> None:
    with pytest.raises(ValidationError):
        _make_transaction(running_balance=1000.00)


def test_transaction_rejects_amount_with_more_than_two_decimal_places() -> None:
    with pytest.raises(ValidationError):
        _make_transaction(amount=Decimal("4.567"))


def test_transaction_rejects_running_balance_with_more_than_two_decimal_places() -> None:
    with pytest.raises(ValidationError):
        _make_transaction(running_balance=Decimal("1000.001"))


def test_transaction_accepts_decimal_from_string() -> None:
    tx = _make_transaction(amount="9.99")
    assert tx.amount == Decimal("9.99")


def test_transaction_is_frozen() -> None:
    tx = _make_transaction()
    with pytest.raises(ValidationError):
        tx.amount = Decimal("1.00")  # type: ignore[misc]


def test_transaction_default_currency_is_cad() -> None:
    tx = _make_transaction()
    assert tx.currency == "CAD"


def test_transaction_default_row_sequence_is_zero() -> None:
    tx = _make_transaction()
    assert tx.row_sequence == 0


def test_transaction_issuer_is_normalized_to_stripped_uppercase() -> None:
    tx = _make_transaction(issuer="  td  ")
    assert tx.issuer == "TD"


def test_transaction_rejects_empty_issuer() -> None:
    with pytest.raises(ValidationError):
        _make_transaction(issuer="   ")


def test_transaction_accepts_novel_issuer_without_code_changes() -> None:
    # AGENTS.md §3: "No per-issuer parsers." A new issuer name must just work.
    tx = _make_transaction(issuer="Scotiabank")
    assert tx.issuer == "SCOTIABANK"


def test_parsed_statement_holds_transactions() -> None:
    tx = _make_transaction()
    stmt = ParsedStatement(
        issuer="TD",
        account_name="TD Rewards Visa",
        account_label="TD ****1234",
        account_type=AccountType.CREDIT,
        period_start=date(2024, 1, 1),
        period_end=date(2024, 1, 31),
        transactions=(tx,),
    )
    assert stmt.transactions == (tx,)


def test_parsed_statement_default_currency_is_cad() -> None:
    stmt = ParsedStatement(
        issuer="TD",
        account_name="TD Rewards Visa",
        account_label="TD ****1234",
        account_type=AccountType.CREDIT,
    )
    assert stmt.currency == "CAD"
