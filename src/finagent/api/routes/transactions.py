"""GET /transactions."""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from finagent.api.deps import get_db, require_auth
from finagent.api.schemas import TransactionOut
from finagent.db.models import Transaction
from finagent.db.repository import list_transactions

router = APIRouter(tags=["transactions"], dependencies=[Depends(require_auth)])


@router.get("/transactions", response_model=list[TransactionOut])
def list_transactions_route(
    account_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    category_id: int | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db),
) -> list[TransactionOut]:
    """List transactions, newest first, with optional filters."""
    rows = list_transactions(
        session,
        account_id=account_id,
        date_from=date_from,
        date_to=date_to,
        category_id=category_id,
        limit=limit,
        offset=offset,
    )
    return [_to_schema(row) for row in rows]


def _to_schema(row: Transaction) -> TransactionOut:
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
        category_source=row.category_source,
        created_at=row.created_at,
    )
