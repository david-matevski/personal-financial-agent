"""Tests for finagent.ingest.validate."""

from datetime import date
from decimal import Decimal

from finagent.domain.models import AccountType, ParsedStatement, Transaction
from finagent.ingest.extract.schema import StatementExtraction
from finagent.ingest.validate import ValidationStatus, validate


def _extraction(**overrides: object) -> StatementExtraction:
    defaults: dict[str, object] = {
        "issuer": "TD",
        "account_name": "TD Rewards Visa",
        "account_last4": "1234",
        "account_type": "CREDIT",
        "currency": "CAD",
        "period_start": "2026-01-01",
        "period_end": "2026-01-31",
        "opening_balance": None,
        "closing_balance": None,
        "total_money_out": None,
        "total_money_in": None,
        "transactions": [],
    }
    defaults.update(overrides)
    return StatementExtraction.model_validate(defaults)


def _tx(**overrides: object) -> Transaction:
    defaults: dict[str, object] = {
        "issuer": "TD",
        "account_type": AccountType.CREDIT,
        "account_label": "TD ****1234",
        "posted_date": date(2026, 1, 15),
        "description": "Fictional Coffee Co",
        "amount": Decimal("5.00"),
    }
    defaults.update(overrides)
    return Transaction.model_validate(defaults)


def _statement(
    transactions: tuple[Transaction, ...],
    account_type: AccountType = AccountType.CREDIT,
    period_start: date | None = date(2026, 1, 1),
    period_end: date | None = date(2026, 1, 31),
) -> ParsedStatement:
    return ParsedStatement(
        issuer="TD",
        account_name="TD Rewards Visa",
        account_label="TD ****1234",
        account_type=account_type,
        period_start=period_start,
        period_end=period_end,
        transactions=transactions,
    )


def test_credit_reconciles_when_sum_matches_balance_delta() -> None:
    extraction = _extraction(opening_balance="100.00", closing_balance="105.00")
    statement = _statement((_tx(amount=Decimal("5.00")),))

    result = validate(extraction, statement)

    assert result.status is ValidationStatus.VERIFIED
    assert result.problems == ()


def test_credit_fails_when_sum_does_not_match_balance_delta() -> None:
    extraction = _extraction(opening_balance="100.00", closing_balance="105.00")
    statement = _statement((_tx(amount=Decimal("10.00")),))

    result = validate(extraction, statement)

    assert result.status is ValidationStatus.FAILED
    assert result.discrepancy == Decimal("5.00")


def test_debit_reconciles_when_money_in_raises_balance() -> None:
    # DEBIT: closing = opening + net money-in, so signed sum == -(closing - opening)
    extraction = _extraction(
        account_type="DEBIT", opening_balance="100.00", closing_balance="105.00"
    )
    tx = _tx(account_type=AccountType.DEBIT, amount=Decimal("-5.00"))
    statement = _statement((tx,), account_type=AccountType.DEBIT)

    result = validate(extraction, statement)

    assert result.status is ValidationStatus.VERIFIED


def test_debit_fails_when_sum_does_not_match_balance_delta() -> None:
    extraction = _extraction(
        account_type="DEBIT", opening_balance="100.00", closing_balance="105.00"
    )
    tx = _tx(account_type=AccountType.DEBIT, amount=Decimal("5.00"))  # wrong sign
    statement = _statement((tx,), account_type=AccountType.DEBIT)

    result = validate(extraction, statement)

    assert result.status is ValidationStatus.FAILED
    assert result.discrepancy is not None


def test_totals_only_path_reconciles() -> None:
    extraction = _extraction(total_money_out="5.00", total_money_in="0.00")
    statement = _statement((_tx(amount=Decimal("5.00")),))

    result = validate(extraction, statement)

    assert result.status is ValidationStatus.VERIFIED


def test_totals_only_path_fails_on_mismatch() -> None:
    extraction = _extraction(total_money_out="9.00")
    statement = _statement((_tx(amount=Decimal("5.00")),))

    result = validate(extraction, statement)

    assert result.status is ValidationStatus.FAILED
    assert result.discrepancy == Decimal("-4.00")


def test_unverified_when_no_totals_printed_at_all() -> None:
    extraction = _extraction()
    statement = _statement((_tx(),))

    result = validate(extraction, statement)

    assert result.status is ValidationStatus.UNVERIFIED
    assert result.problems == ()


def test_fails_when_posted_date_outside_period_window() -> None:
    extraction = _extraction()
    tx = _tx(posted_date=date(2025, 1, 1))  # far before period_start - 45 days
    statement = _statement((tx,))

    result = validate(extraction, statement)

    assert result.status is ValidationStatus.FAILED
    assert any("outside the expected window" in problem for problem in result.problems)


def test_posted_date_within_lookback_window_is_allowed() -> None:
    extraction = _extraction()
    # period_start - 45 days = 2025-11-17; this date is within that window.
    tx = _tx(posted_date=date(2025, 12, 20))
    statement = _statement((tx,))

    result = validate(extraction, statement)

    assert result.status is ValidationStatus.UNVERIFIED


def test_fails_on_zero_transactions() -> None:
    extraction = _extraction()
    statement = _statement(())

    result = validate(extraction, statement)

    assert result.status is ValidationStatus.FAILED
    assert any("no transactions" in problem for problem in result.problems)


def test_problems_never_contain_descriptions() -> None:
    extraction = _extraction(total_money_out="9.00")
    statement = _statement((_tx(description="Totally Secret Merchant Name"),))

    result = validate(extraction, statement)

    for problem in result.problems:
        assert "Totally Secret Merchant Name" not in problem


def test_debit_cr_suffixed_balances_reconcile_as_verified() -> None:
    """A DEBIT (bank) statement printing both balances with a "CR" suffix --
    the common "in credit" confirmation for a normal positive balance --
    must reconcile normally, not be misread as an overdraft/FAILED.
    """
    extraction = _extraction(
        account_type="DEBIT", opening_balance="100.00 CR", closing_balance="105.00 CR"
    )
    tx = _tx(account_type=AccountType.DEBIT, amount=Decimal("-5.00"))
    statement = _statement((tx,), account_type=AccountType.DEBIT)

    result = validate(extraction, statement)

    assert result.status is ValidationStatus.VERIFIED


def test_debit_overdraft_reconciles_with_negative_closing_balance() -> None:
    # Opening 100.00 (healthy), closing overdrawn by 50.00 (DR marker) ->
    # a net swing of 150.00 money out. The DEBIT reconcile formula
    # (signed sum == -(closing - opening)) must still hold with a
    # negative, marker-derived closing balance.
    extraction = _extraction(
        account_type="DEBIT", opening_balance="100.00", closing_balance="50.00DR"
    )
    tx = _tx(account_type=AccountType.DEBIT, amount=Decimal("150.00"))
    statement = _statement((tx,), account_type=AccountType.DEBIT)

    result = validate(extraction, statement)

    assert result.status is ValidationStatus.VERIFIED


def test_notes_from_parsed_statement_surface_in_problems_without_failing() -> None:
    extraction = _extraction(opening_balance="100.00", closing_balance="105.00")
    statement = ParsedStatement(
        issuer="TD",
        account_name="TD Rewards Visa",
        account_label="TD ****1234",
        account_type=AccountType.CREDIT,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        transactions=(_tx(amount=Decimal("5.00")),),
        notes=("direction corrected from printed marker on 1 transaction",),
    )

    result = validate(extraction, statement)

    assert result.status is ValidationStatus.VERIFIED
    assert "direction corrected from printed marker on 1 transaction" in result.problems
