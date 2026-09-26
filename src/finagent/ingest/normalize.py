"""Pure ``StatementExtraction`` -> ``ParsedStatement`` conversion (AGENTS.md §3).

Code, never the model, converts printed amount/date strings and applies the
sign convention: money OUT is positive, money IN is negative. Amounts are
interpreted generically via ``finagent.ingest.amounts.interpret_amount`` --
this module owns only what the printed marker/direction *means* for each
kind of field, never how to parse the characters themselves.
"""

import re
from datetime import date
from decimal import Decimal

from finagent.core.errors import ParseError
from finagent.domain.hashing import assign_row_sequences
from finagent.domain.models import AccountType, ParsedStatement, Transaction
from finagent.ingest.amounts import interpret_amount
from finagent.ingest.extract.schema import ExtractedTransaction, StatementExtraction

_NON_DIGIT_RE = re.compile(r"\D")


def parse_iso_date(raw: str) -> date:
    """Parse an ISO ``YYYY-MM-DD`` date string, raising ``ParseError`` on failure."""
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ParseError(f"Unparseable date: {raw!r}") from exc


def parse_optional_iso_date(raw: str | None) -> date | None:
    """``parse_iso_date``, passing through None."""
    if raw is None:
        return None
    return parse_iso_date(raw)


def normalize_issuer(issuer: str) -> str:
    """Canonical issuer key, shared by account identity and dedup hashes."""
    return issuer.strip().upper()


def normalize_last4(last4: str) -> str:
    """Digits only, last four, so masking/spacing variants map to one account."""
    return _NON_DIGIT_RE.sub("", last4)[-4:]


def _account_label(issuer: str, last4: str) -> str:
    return f"{normalize_issuer(issuer)} ****{normalize_last4(last4)}"


def interpret_balance(raw: str | None, account_type: AccountType) -> Decimal | None:
    """Interpret a printed balance (opening/closing) into a signed ``Decimal``.

    AGENTS.md task spec §2, sign convention (positive = owed/spent).
    ``interpret_amount`` keeps a textual ``CR``/``DR`` marker separate from a
    sign (minus/parentheses) because they mean different things depending on
    account type:

    - CREDIT accounts: ``CR`` text or a sign means the bank owes the holder
      (an overpayment/credit balance), so negative; otherwise positive.
    - DEBIT accounts: a balance is money held, positive by default. ``DR``
      text or a sign means overdrawn, so negative. ``CR`` text on a DEBIT
      balance is the common "in credit" confirmation banks print on a
      perfectly normal positive balance -- it does *not* flip the sign.
    """
    if raw is None:
        return None
    parsed = interpret_amount(raw)
    if account_type is AccountType.CREDIT:
        negative = parsed.marker == "credit" or parsed.negative
    else:
        negative = parsed.marker == "debit" or parsed.negative
    return -parsed.magnitude if negative else parsed.magnitude


def interpret_total(raw: str | None) -> Decimal | None:
    """Printed summary totals are always reported as magnitudes."""
    if raw is None:
        return None
    return interpret_amount(raw).magnitude


def _normalize_transaction(
    extracted: ExtractedTransaction,
    *,
    issuer: str,
    account_type: AccountType,
    account_label: str,
    currency: str,
) -> tuple[Transaction, bool]:
    """Normalize one transaction line; returns (Transaction, direction_corrected).

    The printed marker/sign wins over the model's own ``direction`` reading,
    since the document is the source of truth (AGENTS.md task spec §2):
    ``CR`` text or a sign (minus/parentheses) means money in; ``DR`` text
    means money out (the two can't both be present -- ``interpret_amount``
    rejects that as contradictory). When the printed reading disagrees with
    the model's, ``direction_corrected`` is True so the caller can surface a
    note -- this alone must never fail the statement.
    """
    parsed = interpret_amount(extracted.amount)
    if parsed.marker == "debit":
        effective_direction = "OUT"
    elif parsed.marker == "credit" or parsed.negative:
        effective_direction = "IN"
    else:
        effective_direction = extracted.direction
    printed_a_signal = parsed.marker is not None or parsed.negative
    corrected = printed_a_signal and effective_direction != extracted.direction

    signed_amount = parsed.magnitude if effective_direction == "OUT" else -parsed.magnitude

    tx = Transaction(
        issuer=issuer,
        account_type=account_type,
        account_label=account_label,
        posted_date=parse_iso_date(extracted.posted_date),
        transaction_date=parse_optional_iso_date(extracted.transaction_date),
        description=extracted.description,
        amount=signed_amount,
        currency=currency,
        running_balance=interpret_balance(extracted.running_balance, account_type),
    )
    return tx, corrected


def normalize(extraction: StatementExtraction) -> ParsedStatement:
    """Convert a raw ``StatementExtraction`` into a canonical ``ParsedStatement``."""
    account_type = AccountType(extraction.account_type)
    account_label = _account_label(extraction.issuer, extraction.account_last4)

    transactions: list[Transaction] = []
    corrected_count = 0
    for extracted_tx in extraction.transactions:
        tx, corrected = _normalize_transaction(
            extracted_tx,
            issuer=extraction.issuer,
            account_type=account_type,
            account_label=account_label,
            currency=extraction.currency,
        )
        transactions.append(tx)
        if corrected:
            corrected_count += 1
    transactions = assign_row_sequences(transactions)

    notes: tuple[str, ...] = ()
    if corrected_count:
        plural = "s" if corrected_count != 1 else ""
        notes = (
            f"direction corrected from printed marker on {corrected_count} transaction{plural}",
        )

    return ParsedStatement(
        issuer=extraction.issuer,
        account_name=extraction.account_name,
        account_label=account_label,
        account_type=account_type,
        currency=extraction.currency,
        period_start=parse_optional_iso_date(extraction.period_start),
        period_end=parse_optional_iso_date(extraction.period_end),
        transactions=tuple(transactions),
        notes=notes,
    )
