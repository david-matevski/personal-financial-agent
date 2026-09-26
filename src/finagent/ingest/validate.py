"""Deterministic reconciliation and sanity checks (AGENTS.md §3).

Pure functions: given the raw extraction (for its printed totals) and the
normalized statement, decide whether the transactions can be trusted.
Where the statement prints totals, transactions must reconcile to them;
statements with no printed totals are ``UNVERIFIED``, never ``VERIFIED``.
"""

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from enum import Enum

from finagent.domain.models import AccountType, ParsedStatement, Transaction
from finagent.ingest.extract.schema import StatementExtraction
from finagent.ingest.normalize import interpret_balance, interpret_total

_PERIOD_LOOKBACK_DAYS = 45


class ValidationStatus(str, Enum):
    """The outcome of validating one extraction attempt."""

    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class ValidationResult:
    """The result of validating one ``ParsedStatement`` against its extraction."""

    status: ValidationStatus
    problems: tuple[str, ...] = ()
    discrepancy: Decimal | None = None


def _signed_total(transactions: tuple[Transaction, ...]) -> Decimal:
    return sum((tx.amount for tx in transactions), Decimal("0"))


def _out_total(transactions: tuple[Transaction, ...]) -> Decimal:
    return sum((tx.amount for tx in transactions if tx.amount > 0), Decimal("0"))


def _in_total(transactions: tuple[Transaction, ...]) -> Decimal:
    return sum((-tx.amount for tx in transactions if tx.amount < 0), Decimal("0"))


def validate(extraction: StatementExtraction, parsed: ParsedStatement) -> ValidationResult:
    """Validate a normalized statement against its raw extraction's printed totals.

    Every reconciliation check that has data to check must pass for
    ``VERIFIED``; any failing check makes the whole result ``FAILED``. If no
    printed totals are available at all, the result is ``UNVERIFIED`` (never
    ``VERIFIED`` -- AGENTS.md §3). Date-range, decimal-precision, and
    non-empty checks always run, regardless of whether totals were printed.
    """
    problems: list[str] = []
    # Benign observations (e.g. a printed marker overriding the model's
    # direction) never drive the status decision below; they're merged into
    # the returned problems only for visibility.
    notes: list[str] = list(parsed.notes)
    discrepancy: Decimal | None = None
    reconciled = False

    opening = interpret_balance(extraction.opening_balance, parsed.account_type)
    closing = interpret_balance(extraction.closing_balance, parsed.account_type)
    if opening is not None and closing is not None:
        reconciled = True
        total = _signed_total(parsed.transactions)
        expected = (
            closing - opening if parsed.account_type is AccountType.CREDIT else -(closing - opening)
        )
        diff = total - expected
        if diff != 0:
            discrepancy = diff
            problems.append(
                f"transactions summed to {total}, expected {expected} from opening/closing "
                f"balances (difference {diff})"
            )
    else:
        total_out = interpret_total(extraction.total_money_out)
        total_in = interpret_total(extraction.total_money_in)
        if total_out is not None:
            reconciled = True
            actual_out = _out_total(parsed.transactions)
            diff = actual_out - total_out
            if diff != 0:
                discrepancy = diff
                problems.append(
                    f"money-out transactions summed to {actual_out}, printed total is "
                    f"{total_out} (difference {diff})"
                )
        if total_in is not None:
            reconciled = True
            actual_in = _in_total(parsed.transactions)
            diff = actual_in - total_in
            if diff != 0:
                if discrepancy is None:
                    discrepancy = diff
                problems.append(
                    f"money-in transactions summed to {actual_in}, printed total is "
                    f"{total_in} (difference {diff})"
                )

    if not parsed.transactions:
        problems.append("statement has no transactions")

    lower_bound = (
        parsed.period_start - timedelta(days=_PERIOD_LOOKBACK_DAYS)
        if parsed.period_start is not None
        else None
    )
    for tx in parsed.transactions:
        if (
            lower_bound is not None
            and parsed.period_end is not None
            and not (lower_bound <= tx.posted_date <= parsed.period_end)
        ):
            problems.append(
                f"transaction posted_date {tx.posted_date.isoformat()} is outside the "
                f"expected window [{lower_bound.isoformat()}, {parsed.period_end.isoformat()}]"
            )
        exponent = tx.amount.normalize().as_tuple().exponent
        if isinstance(exponent, int) and exponent < -2:
            problems.append("transaction amount has more than 2 decimal places")

    if problems:
        status = ValidationStatus.FAILED
    elif reconciled:
        status = ValidationStatus.VERIFIED
    else:
        status = ValidationStatus.UNVERIFIED

    return ValidationResult(
        status=status, problems=tuple(problems + notes), discrepancy=discrepancy
    )
