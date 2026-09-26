"""Request/response schemas for the REST API.

Amounts are always serialized as strings, never floats/numbers, so a client
never loses precision decoding JSON (AGENTS.md §3: "Money is Decimal, never
float"). These are plain DTOs; routes build them explicitly from ORM rows
rather than relying on implicit Decimal -> str coercion.
"""

from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator


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


class UploadOut(BaseModel):
    """One row of GET /uploads, and the response body of POST/GET /uploads/{id}.

    ``statement_status``/``transactions_inserted`` are populated once the
    upload is linked to a statement (``statement_id`` set); ``null``
    otherwise. This is the contract the browser UI polls against.
    """

    id: int
    filename: str
    size_bytes: int
    status: str
    error: str | None
    statement_id: int | None
    statement_status: str | None
    transactions_inserted: int | None
    created_at: datetime
    updated_at: datetime


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
    category_name: str | None
    category_source: str | None
    category_confidence: str | None
    needs_review: bool
    created_at: datetime


# categories.id is SMALLINT: bound ids at the edge so an out-of-range value
# is a 422, not a database DataError surfacing as a 500.
CATEGORY_ID_MAX = 32767


class CategoryUpdateRequest(BaseModel):
    """Request body for PATCH /transactions/{id}."""

    category_id: int = Field(ge=1, le=CATEGORY_ID_MAX)


class ConfirmRequest(BaseModel):
    """Request body for POST /transactions/confirm."""

    ids: list[int] = Field(min_length=1, max_length=500)

    @field_validator("ids")
    @classmethod
    def _ids_are_positive(cls, ids: list[int]) -> list[int]:
        if any(i < 1 for i in ids):
            raise ValueError("ids must be >= 1")
        return ids


class ConfirmResponse(BaseModel):
    """Response body for POST /transactions/confirm."""

    confirmed: int


class CategorizeResponse(BaseModel):
    """Response body for POST /transactions/categorize.

    ``remaining`` is how many pool rows are left after this call; with
    ``include_ai``, ``last_id`` is the cursor to pass back as ``after_id``
    to continue paging (``None`` when nothing in the pool was reached).
    """

    categorized: int
    remaining: int
    last_id: int | None = None


class CategoryOut(BaseModel):
    """One row of GET /categories."""

    id: int
    name: str
    parent_id: int | None
    description: str | None
    created_at: datetime


class CategorySummaryOut(BaseModel):
    """One row of GET /categories/summary."""

    category_id: int | None
    category_name: str | None
    money_out: str
    money_in: str
    count: int
