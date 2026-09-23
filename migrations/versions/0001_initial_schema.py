"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-09-23

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SEED_CATEGORIES = [
    "Transportation",
    "Grocery",
    "Dining",
    "Entertainment",
    "Shopping",
    "Subscriptions",
    "Travel",
    "Utilities",
    "Health",
    "Income",
    "Transfer",
    "Fees & Interest",
    "Payment",
    "Other",
]


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("issuer", sa.Text(), nullable=False),
        sa.Column("account_last4", sa.CHAR(4), nullable=False),
        sa.Column("account_type", sa.Text(), nullable=False),
        sa.Column("account_name", sa.Text(), nullable=False),
        sa.Column("currency", sa.CHAR(3), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_accounts")),
        sa.UniqueConstraint("issuer", "account_last4", "account_type", name="uq_accounts_identity"),
        sa.CheckConstraint("account_type IN ('CREDIT', 'DEBIT')", name="ck_accounts_account_type"),
    )

    op.create_table(
        "categories",
        sa.Column("id", sa.SmallInteger(), sa.Identity(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("parent_id", sa.SmallInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_categories")),
        sa.ForeignKeyConstraint(
            ["parent_id"], ["categories.id"], name=op.f("fk_categories_parent_id_categories")
        ),
        sa.UniqueConstraint("name", name="uq_categories_name"),
    )

    op.create_table(
        "statements",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=True),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("file_sha256", sa.CHAR(64), nullable=False),
        sa.Column("media_type", sa.Text(), nullable=True),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("attempts", sa.SmallInteger(), nullable=False),
        sa.Column(
            "problems",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("opening_balance", sa.NUMERIC(14, 2), nullable=True),
        sa.Column("closing_balance", sa.NUMERIC(14, 2), nullable=True),
        sa.Column("total_money_out", sa.NUMERIC(14, 2), nullable=True),
        sa.Column("total_money_in", sa.NUMERIC(14, 2), nullable=True),
        sa.Column("extraction", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("transactions_inserted", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_statements")),
        sa.ForeignKeyConstraint(
            ["account_id"], ["accounts.id"], name=op.f("fk_statements_account_id_accounts")
        ),
        sa.UniqueConstraint("file_sha256", name="uq_statements_file_sha256"),
        sa.CheckConstraint(
            "status IN ('VERIFIED', 'UNVERIFIED', 'FAILED')", name="ck_statements_status"
        ),
    )
    op.create_index(
        "ix_statements_account_id_period_start", "statements", ["account_id", "period_start"]
    )

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

    op.create_table(
        "transactions",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("statement_id", sa.BigInteger(), nullable=False),
        sa.Column("transaction_hash", sa.CHAR(64), nullable=False),
        sa.Column("posted_date", sa.Date(), nullable=False),
        sa.Column("transaction_date", sa.Date(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("amount", sa.NUMERIC(14, 2), nullable=False),
        sa.Column("currency", sa.CHAR(3), nullable=False),
        sa.Column("running_balance", sa.NUMERIC(14, 2), nullable=True),
        sa.Column("row_sequence", sa.SmallInteger(), nullable=False),
        sa.Column("category_id", sa.SmallInteger(), nullable=True),
        sa.Column("category_source", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transactions")),
        sa.ForeignKeyConstraint(
            ["account_id"], ["accounts.id"], name=op.f("fk_transactions_account_id_accounts")
        ),
        sa.ForeignKeyConstraint(
            ["statement_id"],
            ["statements.id"],
            name=op.f("fk_transactions_statement_id_statements"),
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name=op.f("fk_transactions_category_id_categories"),
        ),
        sa.UniqueConstraint("transaction_hash", name="uq_transactions_transaction_hash"),
        sa.CheckConstraint(
            "category_source IN ('rule', 'ai', 'user')", name="ck_transactions_category_source"
        ),
    )
    op.create_index(
        "ix_transactions_account_id_posted_date", "transactions", ["account_id", "posted_date"]
    )
    op.create_index("ix_transactions_posted_date", "transactions", ["posted_date"])
    op.create_index("ix_transactions_category_id", "transactions", ["category_id"])

    categories_table = sa.table(
        "categories",
        sa.column("name", sa.Text()),
    )
    op.bulk_insert(categories_table, [{"name": name} for name in _SEED_CATEGORIES])


def downgrade() -> None:
    op.drop_table("transactions")
    op.drop_table("category_rules")
    op.drop_table("statements")
    op.drop_table("categories")
    op.drop_table("accounts")
