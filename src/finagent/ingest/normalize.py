"""Pure ``StatementExtraction`` -> ``ParsedStatement`` conversion (AGENTS.md §3).

Code, never the model, converts printed amount/date strings and applies the
sign convention: money OUT is positive, money IN is negative.
"""

import re
from datetime import date
from decimal import Decimal, InvalidOperation

from finagent.core.errors import ParseError
from finagent.domain.hashing import assign_row_sequences
from finagent.domain.models import AccountType, ParsedStatement, Transaction
from finagent.ingest.extract.schema import ExtractedTransaction, StatementExtraction

_NON_DIGIT_RE = re.compile(r"\D")


def parse_amount(raw: str) -> Decimal:
    """Parse a printed amount string into a Decimal.

    Accepts a leading "$" and comma thousands separators; any other stray
    character -- including an internal space, e.g. a "1 234,56"-style
    European-format artifact -- is rejected rather than silently
    mis-parsed.
    """
    cleaned = raw.strip().lstrip("$").strip()
    if not cleaned or any(ch.isspace() for ch in cleaned):
        raise ParseError(f"Unparseable amount: {raw!r}")
    cleaned = cleaned.replace(",", "")
    try:
        return Decimal(cleaned)
    except InvalidOperation as exc:
        raise ParseError(f"Unparseable amount: {raw!r}") from exc


def parse_optional_amount(raw: str | None) -> Decimal | None:
    """``parse_amount``, passing through None."""
    if raw is None:
        return None
    return parse_amount(raw)


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


def _normalize_transaction(
    extracted: ExtractedTransaction,
    *,
    issuer: str,
    account_type: AccountType,
    account_label: str,
    currency: str,
) -> Transaction:
    amount = parse_amount(extracted.amount)
    signed_amount = amount if extracted.direction == "OUT" else -amount
    return Transaction(
        issuer=issuer,
        account_type=account_type,
        account_label=account_label,
        posted_date=parse_iso_date(extracted.posted_date),
        transaction_date=parse_optional_iso_date(extracted.transaction_date),
        description=extracted.description,
        amount=signed_amount,
        currency=currency,
        running_balance=parse_optional_amount(extracted.running_balance),
    )


def normalize(extraction: StatementExtraction) -> ParsedStatement:
    """Convert a raw ``StatementExtraction`` into a canonical ``ParsedStatement``."""
    account_type = AccountType(extraction.account_type)
    account_label = _account_label(extraction.issuer, extraction.account_last4)

    transactions = [
        _normalize_transaction(
            tx,
            issuer=extraction.issuer,
            account_type=account_type,
            account_label=account_label,
            currency=extraction.currency,
        )
        for tx in extraction.transactions
    ]
    transactions = assign_row_sequences(transactions)

    return ParsedStatement(
        issuer=extraction.issuer,
        account_name=extraction.account_name,
        account_label=account_label,
        account_type=account_type,
        currency=extraction.currency,
        period_start=parse_optional_iso_date(extraction.period_start),
        period_end=parse_optional_iso_date(extraction.period_end),
        transactions=tuple(transactions),
    )
