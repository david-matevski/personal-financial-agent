"""duplicate protection: overlap reporting and near-duplicate flags

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-26

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "statements",
        sa.Column("transactions_skipped", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "statements",
        sa.Column("period_derived", sa.Boolean(), server_default="false", nullable=False),
    )

    op.add_column(
        "transactions", sa.Column("possible_duplicate_of", sa.BigInteger(), nullable=True)
    )
    op.add_column(
        "transactions",
        sa.Column("duplicate_reviewed", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "transactions", sa.Column("removed_at", sa.TIMESTAMP(timezone=True), nullable=True)
    )
    op.create_foreign_key(
        op.f("fk_transactions_possible_duplicate_of_transactions"),
        "transactions",
        "transactions",
        ["possible_duplicate_of"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_transactions_possible_duplicate_of", "transactions", ["possible_duplicate_of"]
    )


def downgrade() -> None:
    op.drop_index("ix_transactions_possible_duplicate_of", table_name="transactions")
    op.drop_constraint(
        op.f("fk_transactions_possible_duplicate_of_transactions"),
        "transactions",
        type_="foreignkey",
    )
    op.drop_column("transactions", "removed_at")
    op.drop_column("transactions", "duplicate_reviewed")
    op.drop_column("transactions", "possible_duplicate_of")

    op.drop_column("statements", "period_derived")
    op.drop_column("statements", "transactions_skipped")
