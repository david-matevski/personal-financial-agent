"""uploads

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-23

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "uploads",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("file_sha256", sa.CHAR(64), nullable=False),
        sa.Column("media_type", sa.Text(), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("statement_id", sa.BigInteger(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_uploads")),
        sa.ForeignKeyConstraint(
            ["statement_id"],
            ["statements.id"],
            name=op.f("fk_uploads_statement_id_statements"),
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "status IN ('QUEUED', 'PROCESSING', 'DONE', 'ERROR')", name="ck_uploads_status"
        ),
    )
    op.create_index("ix_uploads_status_id", "uploads", ["status", "id"])


def downgrade() -> None:
    op.drop_table("uploads")
