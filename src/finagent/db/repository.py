"""Idempotent persistence of an ``ExtractionResult`` (AGENTS.md §3: dedup).

``save_extraction`` is the single entry point: it upserts the account,
records the statement (whatever its status), and -- for VERIFIED/UNVERIFIED
statements only -- inserts transactions with hash-based dedup. Everything
happens in one transaction; the caller owns commit.
"""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from finagent.db.models import Account, Category, Statement
from finagent.db.models import Transaction as TransactionRow
from finagent.domain.hashing import transaction_hash
from finagent.domain.models import Transaction as DomainTransaction
from finagent.ingest.normalize import normalize_issuer, normalize_last4, parse_optional_amount
from finagent.ingest.pipeline import ExtractionResult
from finagent.ingest.validate import ValidationStatus

_TRUSTED_STATUSES = (ValidationStatus.VERIFIED, ValidationStatus.UNVERIFIED)


@dataclass(frozen=True)
class SavedStatement:
    """The outcome of persisting one ``ExtractionResult``."""

    statement_id: int
    status: ValidationStatus
    transactions_inserted: int
    transactions_skipped_duplicate: int
    already_imported: bool


def save_extraction(
    session: Session,
    *,
    filename: str,
    file_sha256: str,
    media_type: str | None,
    result: ExtractionResult,
    extraction_json: dict[str, object],
    model: str,
) -> SavedStatement:
    """Persist one pipeline ``ExtractionResult``, idempotently.

    Re-saving a file already on record (by ``file_sha256``) writes nothing
    and returns the existing row with ``already_imported=True``. Otherwise
    the account is upserted, the statement is recorded, and -- only for
    VERIFIED/UNVERIFIED statements -- transactions are inserted with
    ``ON CONFLICT (transaction_hash) DO NOTHING``, since a FAILED
    extraction's transactions are not trustworthy (AGENTS.md §3).
    """
    existing = get_statement_by_sha256(session, file_sha256)
    if existing is not None:
        return SavedStatement(
            statement_id=existing.id,
            status=ValidationStatus(existing.status),
            transactions_inserted=existing.transactions_inserted,
            transactions_skipped_duplicate=0,
            already_imported=True,
        )

    statement = result.statement
    extraction = result.extraction
    trusted = result.status in _TRUSTED_STATUSES

    account_id: int | None = None
    if trusted:
        account_id = _upsert_account(
            session,
            issuer=normalize_issuer(extraction.issuer),
            account_last4=normalize_last4(extraction.account_last4),
            account_type=extraction.account_type,
            account_name=extraction.account_name,
            currency=extraction.currency,
            label=statement.account_label,
        )

    statement_row = Statement(
        account_id=account_id,
        filename=filename,
        file_sha256=file_sha256,
        media_type=media_type,
        period_start=statement.period_start,
        period_end=statement.period_end,
        status=result.status.value,
        attempts=result.attempts,
        problems=list(result.problems),
        opening_balance=parse_optional_amount(extraction.opening_balance),
        closing_balance=parse_optional_amount(extraction.closing_balance),
        total_money_out=parse_optional_amount(extraction.total_money_out),
        total_money_in=parse_optional_amount(extraction.total_money_in),
        extraction=extraction_json,
        model=model,
        transactions_inserted=0,
    )
    session.add(statement_row)
    session.flush()  # assigns statement_row.id

    inserted = 0
    skipped = 0
    if trusted and account_id is not None:
        inserted, skipped = _insert_transactions(
            session,
            account_id=account_id,
            statement_id=statement_row.id,
            transactions=statement.transactions,
        )
        statement_row.transactions_inserted = inserted

    return SavedStatement(
        statement_id=statement_row.id,
        status=result.status,
        transactions_inserted=inserted,
        transactions_skipped_duplicate=skipped,
        already_imported=False,
    )


def _upsert_account(
    session: Session,
    *,
    issuer: str,
    account_last4: str,
    account_type: str,
    account_name: str,
    currency: str,
    label: str,
) -> int:
    stmt = (
        pg_insert(Account)
        .values(
            issuer=issuer,
            account_last4=account_last4,
            account_type=account_type,
            account_name=account_name,
            currency=currency,
            label=label,
        )
        .on_conflict_do_update(
            constraint="uq_accounts_identity",
            set_={"account_name": account_name},
        )
        .returning(Account.id)
    )
    return session.execute(stmt).scalar_one()


def _insert_transactions(
    session: Session,
    *,
    account_id: int,
    statement_id: int,
    transactions: tuple[DomainTransaction, ...],
) -> tuple[int, int]:
    if not transactions:
        return 0, 0

    rows = [
        {
            "account_id": account_id,
            "statement_id": statement_id,
            "transaction_hash": transaction_hash(tx),
            "posted_date": tx.posted_date,
            "transaction_date": tx.transaction_date,
            "description": tx.description,
            "amount": tx.amount,
            "currency": tx.currency,
            "running_balance": tx.running_balance,
            "row_sequence": tx.row_sequence,
        }
        for tx in transactions
    ]

    stmt = (
        pg_insert(TransactionRow)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["transaction_hash"])
        .returning(TransactionRow.id)
    )
    inserted_ids = session.execute(stmt).scalars().all()
    inserted = len(inserted_ids)
    skipped = len(rows) - inserted
    return inserted, skipped


# --- Read-only lookups for the API (AGENTS.md: no business logic in routes) ---


def get_statement_by_sha256(session: Session, file_sha256: str) -> Statement | None:
    """Look up a statement by content hash, e.g. to skip re-extraction on re-upload."""
    return session.execute(
        select(Statement).where(Statement.file_sha256 == file_sha256)
    ).scalar_one_or_none()


def get_statement(session: Session, statement_id: int) -> Statement | None:
    """Look up a statement by id."""
    return session.get(Statement, statement_id)


def list_statements(
    session: Session, *, status: str | None = None, limit: int = 50, offset: int = 0
) -> list[Statement]:
    """List statements, newest first, optionally filtered by status."""
    stmt = select(Statement).order_by(Statement.id.desc()).limit(limit).offset(offset)
    if status is not None:
        stmt = stmt.where(Statement.status == status)
    return list(session.execute(stmt).scalars().all())


def list_accounts(session: Session) -> list[Account]:
    """List every account."""
    return list(session.execute(select(Account).order_by(Account.id)).scalars().all())


def list_transactions(
    session: Session,
    *,
    account_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    category_id: int | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[TransactionRow]:
    """List transactions, newest first, with optional filters."""
    stmt = select(TransactionRow).order_by(
        TransactionRow.posted_date.desc(), TransactionRow.id.desc()
    )
    if account_id is not None:
        stmt = stmt.where(TransactionRow.account_id == account_id)
    if date_from is not None:
        stmt = stmt.where(TransactionRow.posted_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(TransactionRow.posted_date <= date_to)
    if category_id is not None:
        stmt = stmt.where(TransactionRow.category_id == category_id)
    stmt = stmt.limit(limit).offset(offset)
    return list(session.execute(stmt).scalars().all())


def list_categories(session: Session) -> list[Category]:
    """List every category."""
    return list(session.execute(select(Category).order_by(Category.id)).scalars().all())
