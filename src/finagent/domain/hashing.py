"""Deterministic dedup hashing for transactions (AGENTS.md §3).

Every transaction gets a SHA-256 hash used for ``ON CONFLICT DO NOTHING``
inserts, so re-importing the same statement is a no-op.
"""

import hashlib
import re
from collections import defaultdict
from decimal import Decimal

from finagent.domain.models import AccountType, Transaction

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_description(description: str) -> str:
    """Collapse internal whitespace, uppercase, and strip the description."""
    return _WHITESPACE_RE.sub(" ", description).strip().upper()


def normalize_account_label(account_label: str) -> str:
    """Strip and uppercase an account label for use as a dedup key."""
    return account_label.strip().upper()


def _format_amount(amount: Decimal) -> str:
    """Render a Decimal amount as a fixed 2-decimal-place string."""
    return f"{amount:.2f}"


def transaction_hash(tx: Transaction) -> str:
    """Compute the deterministic SHA-256 dedup hash for a transaction.

    Debit accounts key on ``running_balance`` (each line has a distinct
    balance snapshot). Credit accounts have no reliable running balance, so
    they key on ``row_sequence`` instead, which disambiguates otherwise
    identical duplicate lines within one statement. ``account_label`` is
    included so two accounts of the same issuer/type (e.g. two TD Visa
    cards) never collide.
    """
    normalized_description = normalize_description(tx.description)
    parts = [
        tx.issuer.value,
        tx.account_type.value,
        normalize_account_label(tx.account_label),
        tx.posted_date.isoformat(),
        normalized_description,
        _format_amount(tx.amount),
    ]
    if tx.account_type is AccountType.DEBIT:
        balance = "" if tx.running_balance is None else _format_amount(tx.running_balance)
        parts.append(balance)
    else:
        parts.append(str(tx.row_sequence))

    digest_input = "|".join(parts)
    return hashlib.sha256(digest_input.encode("utf-8")).hexdigest()


def assign_row_sequences(txs: list[Transaction]) -> list[Transaction]:
    """Assign 0-based row sequences to transactions that share a dedup key.

    Transactions are grouped by (account_label, posted_date, normalized
    description, amount); within each group, sequences are assigned
    0, 1, 2, ... in the order the transactions appear in ``txs``. This
    disambiguates duplicate lines (e.g. two identical $5 coffee charges on
    the same day on the same card).
    """
    counters: dict[tuple[str, str, str, Decimal], int] = defaultdict(int)
    result: list[Transaction] = []
    for tx in txs:
        key = (
            normalize_account_label(tx.account_label),
            tx.posted_date.isoformat(),
            normalize_description(tx.description),
            tx.amount,
        )
        sequence = counters[key]
        counters[key] += 1
        result.append(tx.model_copy(update={"row_sequence": sequence}))
    return result
