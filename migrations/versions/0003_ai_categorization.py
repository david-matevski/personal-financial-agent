"""ai categorization

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-26

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CATEGORY_DESCRIPTIONS = {
    "Transportation": "gas stations, parking, public transit, rideshare, tolls",
    "Grocery": "supermarkets, food stores, liquor stores",
    "Dining": "restaurants, cafes, fast food, bars",
    "Entertainment": "movies, streaming, games, events, hobbies",
    "Shopping": "retail, clothing, electronics, general merchandise",
    "Subscriptions": "recurring software, media, and membership charges",
    "Travel": "flights, hotels, car rentals, travel agencies",
    "Utilities": "electricity, gas, water, internet, phone bills",
    "Health": "pharmacies, doctors, dentists, fitness, insurance",
    "Income": "salary, deposits, interest earned, other incoming funds",
    "Transfer": "money moved between the owner's own accounts",
    "Fees & Interest": "bank fees, interest charges, foreign exchange fees",
    "Payment": "credit card bill payments received",
    "Other": "anything that doesn't fit another category",
}


def upgrade() -> None:
    op.drop_table("category_rules")

    op.add_column("categories", sa.Column("description", sa.Text(), nullable=True))
    categories_table = sa.table(
        "categories",
        sa.column("name", sa.Text()),
        sa.column("description", sa.Text()),
    )
    for name, description in _CATEGORY_DESCRIPTIONS.items():
        op.execute(
            categories_table.update()
            .where(categories_table.c.name == name)
            .values(description=description)
        )

    op.add_column("transactions", sa.Column("category_confidence", sa.NUMERIC(4, 3), nullable=True))
    op.add_column(
        "transactions",
        sa.Column("categorized_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )

    # Any existing 'rule' rows predate this migration's category_source
    # values and have no confidence/categorized_at to go with them --
    # cleared to NULL (uncategorized) rather than kept under a value the new
    # CHECK constraint no longer allows.
    op.execute(
        "UPDATE transactions SET category_id = NULL, category_source = NULL "
        "WHERE category_source = 'rule'"
    )

    op.drop_constraint("ck_transactions_category_source", "transactions", type_="check")
    op.create_check_constraint(
        "ck_transactions_category_source", "transactions", "category_source IN ('ai', 'user')"
    )


def downgrade() -> None:
    op.drop_constraint("ck_transactions_category_source", "transactions", type_="check")
    op.create_check_constraint(
        "ck_transactions_category_source",
        "transactions",
        "category_source IN ('rule', 'ai', 'user')",
    )

    op.drop_column("transactions", "categorized_at")
    op.drop_column("transactions", "category_confidence")

    op.drop_column("categories", "description")

    op.create_table(
        "category_rules",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("pattern", sa.Text(), nullable=False),
        sa.Column("category_id", sa.SmallInteger(), nullable=False),
        sa.Column("priority", sa.Integer(), server_default="100", nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("confidence", sa.NUMERIC(4, 3), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_category_rules")),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name=op.f("fk_category_rules_category_id_categories"),
        ),
        sa.UniqueConstraint("pattern", name="uq_category_rules_pattern"),
        sa.CheckConstraint(
            "created_by IN ('seed', 'user', 'ai')", name="ck_category_rules_created_by"
        ),
    )
    op.create_index("ix_category_rules_priority", "category_rules", ["priority"])
