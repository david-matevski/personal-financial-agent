"""Typed SQLAlchemy 2.x ORM models (AGENTS.md §3).

Money columns are ``NUMERIC(14,2)``; timestamps are ``TIMESTAMPTZ DEFAULT
now()``. Enum-like text columns use CHECK constraints rather than PG ENUM
types, since CHECK constraints are easier to migrate later.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Identity,
    Index,
    LargeBinary,
    SmallInteger,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import CHAR, JSONB, NUMERIC, TEXT, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column, relationship

from finagent.db.base import Base


class Account(Base):
    """A distinct account, identified by (issuer, last4, account_type)."""

    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("issuer", "account_last4", "account_type", name="uq_accounts_identity"),
        CheckConstraint("account_type IN ('CREDIT', 'DEBIT')", name="ck_accounts_account_type"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    issuer: Mapped[str] = mapped_column(TEXT, nullable=False)
    account_last4: Mapped[str] = mapped_column(CHAR(4), nullable=False)
    account_type: Mapped[str] = mapped_column(TEXT, nullable=False)
    account_name: Mapped[str] = mapped_column(TEXT, nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    label: Mapped[str] = mapped_column(TEXT, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )

    statements: Mapped[list["Statement"]] = relationship(back_populates="account")
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="account")


class Statement(Base):
    """One import attempt of a statement file."""

    __tablename__ = "statements"
    __table_args__ = (
        CheckConstraint(
            "status IN ('VERIFIED', 'UNVERIFIED', 'FAILED')", name="ck_statements_status"
        ),
        Index("ix_statements_account_id_period_start", "account_id", "period_start"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    filename: Mapped[str] = mapped_column(TEXT, nullable=False)
    file_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False, unique=True)
    media_type: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(TEXT, nullable=False)
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    problems: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    opening_balance: Mapped[Decimal | None] = mapped_column(NUMERIC(14, 2), nullable=True)
    closing_balance: Mapped[Decimal | None] = mapped_column(NUMERIC(14, 2), nullable=True)
    total_money_out: Mapped[Decimal | None] = mapped_column(NUMERIC(14, 2), nullable=True)
    total_money_in: Mapped[Decimal | None] = mapped_column(NUMERIC(14, 2), nullable=True)
    extraction: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    model: Mapped[str] = mapped_column(TEXT, nullable=False)
    transactions_inserted: Mapped[int] = mapped_column(nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )

    account: Mapped["Account | None"] = relationship(back_populates="statements")
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="statement")


class Upload(Base):
    """One async-upload job: raw bytes queued for the worker to extract.

    ``data`` holds the raw file only until it has been processed (DONE or
    ERROR), then is set to NULL -- we don't retain raw statements once
    extracted (AGENTS.md §6). ``error`` is a safe, generic message only,
    never document content.
    """

    __tablename__ = "uploads"
    __table_args__ = (
        CheckConstraint(
            "status IN ('QUEUED', 'PROCESSING', 'DONE', 'ERROR')", name="ck_uploads_status"
        ),
        Index("ix_uploads_status_id", "status", "id"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    filename: Mapped[str] = mapped_column(TEXT, nullable=False)
    file_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    media_type: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    size_bytes: Mapped[int] = mapped_column(nullable=False)
    data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    status: Mapped[str] = mapped_column(TEXT, nullable=False)
    statement_id: Mapped[int | None] = mapped_column(
        ForeignKey("statements.id", ondelete="SET NULL"), nullable=True
    )
    error: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )

    statement: Mapped["Statement | None"] = relationship()


class Category(Base):
    """A transaction category, optionally nested under a parent category."""

    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(SmallInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(TEXT, nullable=False, unique=True)
    parent_id: Mapped[int | None] = mapped_column(
        SmallInteger, ForeignKey("categories.id"), nullable=True
    )
    description: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )

    transactions: Mapped[list["Transaction"]] = relationship(back_populates="category")


class Transaction(Base):
    """A single normalized, deduplicated transaction line."""

    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint(
            "category_source IN ('ai', 'user')", name="ck_transactions_category_source"
        ),
        Index("ix_transactions_account_id_posted_date", "account_id", "posted_date"),
        Index("ix_transactions_posted_date", "posted_date"),
        Index("ix_transactions_category_id", "category_id"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    statement_id: Mapped[int] = mapped_column(ForeignKey("statements.id"), nullable=False)
    transaction_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False, unique=True)
    posted_date: Mapped[date] = mapped_column(Date, nullable=False)
    transaction_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    description: Mapped[str] = mapped_column(TEXT, nullable=False)
    amount: Mapped[Decimal] = mapped_column(NUMERIC(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    running_balance: Mapped[Decimal | None] = mapped_column(NUMERIC(14, 2), nullable=True)
    row_sequence: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    category_id: Mapped[int | None] = mapped_column(
        SmallInteger, ForeignKey("categories.id"), nullable=True
    )
    category_source: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    category_confidence: Mapped[Decimal | None] = mapped_column(NUMERIC(4, 3), nullable=True)
    categorized_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )

    account: Mapped["Account"] = relationship(back_populates="transactions")
    statement: Mapped["Statement"] = relationship(back_populates="transactions")
    category: Mapped["Category | None"] = relationship(back_populates="transactions")
