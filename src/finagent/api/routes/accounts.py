"""GET /accounts."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from finagent.api.deps import get_db, require_auth
from finagent.api.schemas import AccountOut
from finagent.db.models import Account
from finagent.db.repository import list_accounts

router = APIRouter(tags=["accounts"], dependencies=[Depends(require_auth)])


@router.get("/accounts", response_model=list[AccountOut])
def list_accounts_route(session: Session = Depends(get_db)) -> list[AccountOut]:
    """List every account."""
    return [_to_schema(row) for row in list_accounts(session)]


def _to_schema(row: Account) -> AccountOut:
    return AccountOut(
        id=row.id,
        issuer=row.issuer,
        account_last4=row.account_last4,
        account_type=row.account_type,
        account_name=row.account_name,
        currency=row.currency,
        label=row.label,
        created_at=row.created_at,
    )
