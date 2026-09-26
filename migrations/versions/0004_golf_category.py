"""golf category

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-26

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NAME = "Golf"
_DESCRIPTION = "golf courses, green fees, driving ranges, golf simulators, golf shops and lessons"


def upgrade() -> None:
    # Idempotent-safe: a rerun (e.g. after a failed migration run) must not
    # violate the categories.name unique constraint.
    conn = op.get_bind()
    exists = conn.execute(
        sa.text("SELECT 1 FROM categories WHERE name = :name"), {"name": _NAME}
    ).first()
    if exists is None:
        categories_table = sa.table(
            "categories",
            sa.column("name", sa.Text()),
            sa.column("description", sa.Text()),
        )
        op.bulk_insert(categories_table, [{"name": _NAME, "description": _DESCRIPTION}])


def downgrade() -> None:
    conn = op.get_bind()
    row = conn.execute(
        sa.text("SELECT id FROM categories WHERE name = :name"), {"name": _NAME}
    ).first()
    if row is None:
        return
    category_id = row[0]
    conn.execute(
        sa.text(
            "UPDATE transactions SET category_id = NULL, category_source = NULL, "
            "category_confidence = NULL, categorized_at = NULL WHERE category_id = :category_id"
        ),
        {"category_id": category_id},
    )
    conn.execute(
        sa.text("DELETE FROM categories WHERE id = :category_id"), {"category_id": category_id}
    )
