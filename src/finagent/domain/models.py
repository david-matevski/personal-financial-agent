"""Pure domain models: no I/O, no framework dependencies beyond pydantic.

Sign convention (AGENTS.md §3): positive amount = money out (purchases,
fees); negative amount = money in (payments, refunds, income).
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator

# A free-form, normalized issuer name (AGENTS.md §3: "No per-issuer
# parsers"). New issuers must work without new code, so this is not an
# enum -- just a short canonical name the extraction model reports (e.g.
# "TD", "AMEX", "CIBC", "RBC"), normalized to stripped uppercase.
Issuer = Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, min_length=1)]


class AccountType(str, Enum):
    """The kind of account a statement belongs to."""

    CREDIT = "CREDIT"
    DEBIT = "DEBIT"


def _reject_float_amount(value: Any) -> Any:
    """Pydantic pre-validator: refuse float input for Decimal money fields.

    Floats silently lose precision, which is unacceptable for money (AGENTS.md
    §3: "Money is Decimal, never float"). Callers must pass a Decimal or a str.
    """
    if isinstance(value, float):
        raise ValueError("amount must be a Decimal or str, not float")
    return value


class Transaction(BaseModel):
    """A single, normalized transaction line from a statement."""

    model_config = ConfigDict(frozen=True)

    issuer: Issuer
    account_type: AccountType
    account_label: str
    posted_date: date
    transaction_date: date | None = None
    description: str
    amount: Decimal
    currency: str = "CAD"
    running_balance: Decimal | None = None
    row_sequence: int = 0

    @field_validator("amount", "running_balance", mode="before")
    @classmethod
    def _money_fields_not_float(cls, value: Any) -> Any:
        return _reject_float_amount(value)

    @field_validator("amount", "running_balance")
    @classmethod
    def _money_fields_max_two_decimals(cls, value: Decimal | None) -> Decimal | None:
        if value is None:
            return value
        exponent = value.normalize().as_tuple().exponent
        if isinstance(exponent, int) and exponent < -2:
            raise ValueError(f"amount must have at most 2 decimal places, got {value}")
        return value


class ParsedStatement(BaseModel):
    """The output of parsing one statement document."""

    model_config = ConfigDict(frozen=True)

    issuer: Issuer
    account_name: str
    account_label: str
    account_type: AccountType
    currency: str = "CAD"
    period_start: date | None = None
    period_end: date | None = None
    transactions: tuple[Transaction, ...] = ()
    notes: tuple[str, ...] = ()
    """Benign, non-failing observations from normalization (AGENTS.md task
    spec): e.g. a printed CR/DR marker overriding the model's own direction
    reading. Never affects VERIFIED/UNVERIFIED/FAILED status by itself --
    ``validate.py`` folds these into ``ValidationResult.problems`` purely
    for visibility.
    """
    period_derived: bool = False
    """True when ``period_start``/``period_end`` (or one of them) weren't
    printed on the statement and were instead derived from the min/max
    transaction posted date. Validation's date-window check must not run
    against a derived period -- it would trivially pass.
    """


@dataclass(frozen=True)
class KnownAccount:
    """One account already on record, offered to the extractor as context.

    Lets the model return the exact issuer name already on file (e.g. "TD"
    rather than "TD BANK") when a statement's last 4 digits and account type
    match an account the owner has imported before, so accounts don't drift
    apart into duplicates. ``db.repository.list_known_accounts`` builds
    these from the ``accounts`` table.
    """

    issuer: str
    account_last4: str
    account_type: AccountType
    account_name: str
