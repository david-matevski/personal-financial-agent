"""Tests for finagent.ingest.amounts.interpret_amount (AGENTS.md §3).

Parametrized over many synthetic printed-amount strings -- issuer-agnostic,
no per-issuer branching in the implementation under test.
"""

from decimal import Decimal

import pytest

from finagent.core.errors import ParseError
from finagent.ingest.amounts import interpret_amount


@pytest.mark.parametrize(
    ("raw", "magnitude", "marker", "negative"),
    [
        ("$270.46CR", "270.46", "credit", False),
        ("270.46 CR", "270.46", "credit", False),
        ("CR 270.46", "270.46", "credit", False),
        ("-270.46", "270.46", None, True),
        ("−270.46", "270.46", None, True),  # noqa: RUF001 -- unicode minus sign
        ("270.46-", "270.46", None, True),
        ("(1,234.56)", "1234.56", None, True),
        ("1 234,56 $", "1234.56", None, False),
        ("1.234,56 €", "1234.56", None, False),
        ("1'234.56", "1234.56", None, False),
        ("$1,234.56 DR", "1234.56", "debit", False),
        ("USD 12.00", "12.00", None, False),
        ("0.99", "0.99", None, False),
        ("1,234", "1234", None, False),  # the thousands case
        ("12,5", "12.50", None, False),
        ("12.00", "12.00", None, False),
        ("CAD 5.00", "5.00", None, False),
        ("5.00 CAD", "5.00", None, False),
        ("CA$5.00", "5.00", None, False),
        ("C$5.00", "5.00", None, False),
        ("US$5.00", "5.00", None, False),
        ("£5.00", "5.00", None, False),  # GBP symbol
        ("Cr. 270.46", "270.46", "credit", False),
        ("270.46 Cr.", "270.46", "credit", False),
        ("270.46 DB", "270.46", "debit", False),
        ("+45.00", "45.00", None, False),  # a leading '+' is not a marker
        # CR text and a sign both present: reinforcing, not contradictory.
        ("(270.46) CR", "270.46", "credit", True),
        ("-270.46 CR", "270.46", "credit", True),
    ],
)
def test_interpret_amount_accepts(
    raw: str, magnitude: str, marker: str | None, negative: bool
) -> None:
    result = interpret_amount(raw)
    assert result.magnitude == Decimal(magnitude)
    assert result.marker == marker
    assert result.negative is negative


@pytest.mark.parametrize(
    "raw",
    [
        "12.345.67",
        "1,23,456",
        "abc",
        "",
        "   ",
        "12.345",  # three decimal places, not thousands (see module docstring)
        "$",
        "CR",
        "1..23",
        "1,,23",
    ],
)
def test_interpret_amount_rejects(raw: str) -> None:
    with pytest.raises(ParseError) as exc_info:
        interpret_amount(raw)
    assert raw not in str(exc_info.value) or raw == ""


def test_interpret_amount_rejects_more_than_two_decimal_places_with_both_separators() -> None:
    with pytest.raises(ParseError):
        interpret_amount("1,234.567")


def test_interpret_amount_rejects_conflicting_text_markers() -> None:
    with pytest.raises(ParseError):
        interpret_amount("CR 270.46 DR")


def test_interpret_amount_rejects_debit_text_with_a_sign() -> None:
    """A debit marker plus a sign is contradictory: text says owed, sign says negative."""
    with pytest.raises(ParseError):
        interpret_amount("-270.46 DR")


def test_interpret_amount_error_never_echoes_raw_text() -> None:
    raw = "garbage-amount-xyz"
    with pytest.raises(ParseError) as exc_info:
        interpret_amount(raw)
    assert raw not in str(exc_info.value)


def test_interpret_amount_magnitude_is_never_negative() -> None:
    result = interpret_amount("-5.00")
    assert result.magnitude >= 0
