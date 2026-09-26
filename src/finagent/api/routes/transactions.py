"""GET /transactions, PATCH /transactions/{id}, POST /transactions/categorize."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from finagent.api.deps import get_categorizer, get_db, require_auth
from finagent.api.schemas import (
    CategorizeResponse,
    CategoryUpdateRequest,
    TransactionOut,
)
from finagent.categorize.base import TransactionCategorizer
from finagent.categorize.service import categorize_transactions
from finagent.core.config import Settings, get_settings
from finagent.db.models import Transaction
from finagent.db.repository import (
    get_category,
    get_transaction,
    list_transactions,
    set_transaction_category_by_user,
)

router = APIRouter(tags=["transactions"], dependencies=[Depends(require_auth)])

_CATEGORIZE_LIMIT = 200


@router.get("/transactions", response_model=list[TransactionOut])
def list_transactions_route(
    account_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    category_id: int | None = None,
    needs_review: bool | None = None,
    uncategorized: bool | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[TransactionOut]:
    """List transactions, newest first, with optional filters."""
    rows = list_transactions(
        session,
        account_id=account_id,
        date_from=date_from,
        date_to=date_to,
        category_id=category_id,
        needs_review=needs_review,
        review_threshold=settings.categorization_review_threshold,
        uncategorized=uncategorized,
        limit=limit,
        offset=offset,
    )
    return [_to_schema(row, settings) for row in rows]


@router.patch("/transactions/{transaction_id}", response_model=TransactionOut)
def update_transaction_category_route(
    transaction_id: int,
    body: CategoryUpdateRequest,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TransactionOut:
    """Apply the owner's own categorization choice, overriding any AI guess."""
    if get_transaction(session, transaction_id) is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    if get_category(session, body.category_id) is None:
        raise HTTPException(status_code=422, detail="Unknown category_id")

    row = set_transaction_category_by_user(session, transaction_id, body.category_id)
    assert row is not None  # existence just checked above, same session
    return _to_schema(row, settings)


@router.post("/transactions/categorize", response_model=CategorizeResponse)
def categorize_transactions_route(
    session: Session = Depends(get_db),
    categorizer: TransactionCategorizer = Depends(get_categorizer),
) -> CategorizeResponse:
    """Run AI categorization synchronously over up to 200 uncategorized transactions."""
    count = categorize_transactions(session, categorizer, limit=_CATEGORIZE_LIMIT)
    return CategorizeResponse(categorized=count)


def _to_schema(row: Transaction, settings: Settings) -> TransactionOut:
    needs_review = row.category_id is None or (
        row.category_source == "ai"
        and row.category_confidence is not None
        and row.category_confidence < settings.categorization_review_threshold
    )
    return TransactionOut(
        id=row.id,
        account_id=row.account_id,
        statement_id=row.statement_id,
        posted_date=row.posted_date,
        transaction_date=row.transaction_date,
        description=row.description,
        amount=str(row.amount),
        currency=row.currency,
        running_balance=None if row.running_balance is None else str(row.running_balance),
        category_id=row.category_id,
        category_name=row.category.name if row.category is not None else None,
        category_source=row.category_source,
        category_confidence=(
            None if row.category_confidence is None else str(row.category_confidence)
        ),
        needs_review=needs_review,
        created_at=row.created_at,
    )
