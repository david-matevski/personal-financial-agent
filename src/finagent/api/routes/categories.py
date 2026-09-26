"""GET /categories, GET /categories/summary."""

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from finagent.api.deps import get_db, require_auth
from finagent.api.schemas import CategoryOut, CategorySummaryOut
from finagent.db.models import Category
from finagent.db.repository import CategorySummaryRow, category_summary, list_categories

router = APIRouter(tags=["categories"], dependencies=[Depends(require_auth)])


@router.get("/categories", response_model=list[CategoryOut])
def list_categories_route(session: Session = Depends(get_db)) -> list[CategoryOut]:
    """List every category."""
    return [_to_schema(row) for row in list_categories(session)]


@router.get("/categories/summary", response_model=list[CategorySummaryOut])
def category_summary_route(
    date_from: date | None = None,
    date_to: date | None = None,
    account_id: int | None = None,
    session: Session = Depends(get_db),
) -> list[CategorySummaryOut]:
    """Sum transactions by category (including an uncategorized group), by money_out desc."""
    rows = category_summary(session, date_from=date_from, date_to=date_to, account_id=account_id)
    return [_summary_to_schema(row) for row in rows]


def _to_schema(row: Category) -> CategoryOut:
    return CategoryOut(
        id=row.id,
        name=row.name,
        parent_id=row.parent_id,
        description=row.description,
        created_at=row.created_at,
    )


def _summary_to_schema(row: CategorySummaryRow) -> CategorySummaryOut:
    return CategorySummaryOut(
        category_id=row.category_id,
        category_name=row.category_name,
        money_out=str(row.money_out),
        money_in=str(row.money_in),
        count=row.count,
    )
