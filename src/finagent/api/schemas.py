"""Request/response schemas for the REST API.

Amounts are always serialized as strings, never floats/numbers, so a client
never loses precision decoding JSON (AGENTS.md §3: "Money is Decimal, never
float"). These are plain DTOs; routes build them explicitly from ORM rows
rather than relying on implicit Decimal -> str coercion.
"""

from datetime import date, datetime

from pydantic import BaseModel


class UploadResponse(BaseModel):
    """Response body for POST /statements."""

    statement_id: int
    status: str
    attempts: int
    problems: list[str]
    transactions_inserted: int
    transactions_skipped_duplicate: int
    already_imported: bool


class StatementSummary(BaseModel):
    """One row of GET /statements, and the base of the detail response."""

    id: int
    account_id: int | None
    filename: str
    file_sha256: str
    media_type: str | None
    status: str
    attempts: int
    problems: list[str]
    period_start: date | None
    period_end: date | None
    opening_balance: str | None
    closing_balance: str | None
    total_money_out: str | None
    total_money_in: str | None
    model: str
    transactions_inserted: int
    created_at: datetime


class StatementDetail(StatementSummary):
    """GET /statements/{id}. ``extraction`` is only populated on request."""

    extraction: dict[str, object] | None = None


class AccountOut(BaseModel):
    """One row of GET /accounts."""

    id: int
    issuer: str
    account_last4: str
    account_type: str
    account_name: str
    currency: str
    label: str
    created_at: datetime


class TransactionOut(BaseModel):
    """One row of GET /transactions."""

    id: int
    account_id: int
    statement_id: int
    posted_date: date
    transaction_date: date | None
    description: str
    amount: str
    currency: str
    running_balance: str | None
    category_id: int | None
    category_source: str | None
    created_at: datetime


class CategoryOut(BaseModel):
    """One row of GET /categories."""

    id: int
    name: str
    parent_id: int | None
    created_at: datetime
