"""GET /categories."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from finagent.api.deps import get_db, require_auth
from finagent.api.schemas import CategoryOut
from finagent.db.models import Category
from finagent.db.repository import list_categories

router = APIRouter(tags=["categories"], dependencies=[Depends(require_auth)])


@router.get("/categories", response_model=list[CategoryOut])
def list_categories_route(session: Session = Depends(get_db)) -> list[CategoryOut]:
    """List every category."""
    return [_to_schema(row) for row in list_categories(session)]


def _to_schema(row: Category) -> CategoryOut:
    return CategoryOut(
        id=row.id,
        name=row.name,
        parent_id=row.parent_id,
        created_at=row.created_at,
    )
