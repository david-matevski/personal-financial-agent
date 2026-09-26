"""Idempotent persistence of an ``ExtractionResult`` (AGENTS.md §3: dedup).

``save_extraction`` is the single entry point: it upserts the account,
records the statement (whatever its status), and -- for VERIFIED/UNVERIFIED
statements only -- inserts transactions with hash-based dedup. Everything
happens in one transaction; the caller owns commit.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import and_, case, func, not_, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from finagent.db.models import Account, Category, Statement, Upload
from finagent.db.models import Transaction as TransactionRow
from finagent.domain.hashing import transaction_hash
from finagent.domain.models import Transaction as DomainTransaction
from finagent.ingest.normalize import (
    interpret_balance,
    interpret_total,
    normalize_issuer,
    normalize_last4,
)
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
        opening_balance=interpret_balance(extraction.opening_balance, statement.account_type),
        closing_balance=interpret_balance(extraction.closing_balance, statement.account_type),
        total_money_out=interpret_total(extraction.total_money_out),
        total_money_in=interpret_total(extraction.total_money_in),
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
    needs_review: bool | None = None,
    review_threshold: Decimal = Decimal("0.7"),
    uncategorized: bool | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[TransactionRow]:
    """List transactions, newest first, with optional filters.

    ``needs_review`` matches rows that are uncategorized, or AI-categorized
    below ``review_threshold`` (the same rule as ``TransactionOut.needs_review``
    in the API schema -- kept here so GET /transactions can filter on it
    server-side instead of the client re-deriving it per row).
    """
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
    if uncategorized:
        stmt = stmt.where(TransactionRow.category_id.is_(None))
    if needs_review is not None:
        review_condition = or_(
            TransactionRow.category_id.is_(None),
            and_(
                TransactionRow.category_source == "ai",
                TransactionRow.category_confidence < review_threshold,
            ),
        )
        stmt = stmt.where(review_condition if needs_review else not_(review_condition))
    stmt = stmt.limit(limit).offset(offset)
    return list(session.execute(stmt).scalars().all())


def get_transaction(session: Session, transaction_id: int) -> TransactionRow | None:
    """Look up a transaction by id."""
    return session.get(TransactionRow, transaction_id)


def set_transaction_category_by_user(
    session: Session, transaction_id: int, category_id: int
) -> TransactionRow | None:
    """Apply the owner's own categorization choice, overriding any AI guess.

    Clears ``category_confidence`` (a user choice has no confidence score)
    and stamps ``categorized_at``; ``category_source`` becomes ``'user'``,
    which ``categorize_transactions`` never overwrites.
    """
    row = session.get(TransactionRow, transaction_id)
    if row is None:
        return None
    row.category_id = category_id
    row.category_source = "user"
    row.category_confidence = None
    row.categorized_at = datetime.now(timezone.utc)
    session.flush()
    return row


def list_categories(session: Session) -> list[Category]:
    """List every category."""
    return list(session.execute(select(Category).order_by(Category.id)).scalars().all())


def get_category(session: Session, category_id: int) -> Category | None:
    """Look up a category by id."""
    return session.get(Category, category_id)


@dataclass(frozen=True)
class CategorySummaryRow:
    """One row of the GET /categories/summary aggregate."""

    category_id: int | None
    category_name: str | None
    money_out: Decimal
    money_in: Decimal
    count: int


def category_summary(
    session: Session,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    account_id: int | None = None,
) -> list[CategorySummaryRow]:
    """Sum transactions by category (NULL = uncategorized), ordered by money_out desc.

    ``money_out`` sums positive amounts (AGENTS.md sign convention: positive
    = money out); ``money_in`` sums the absolute value of negative amounts.
    """
    money_out_expr = func.coalesce(
        func.sum(case((TransactionRow.amount > 0, TransactionRow.amount), else_=0)), 0
    )
    money_in_expr = func.coalesce(
        func.sum(case((TransactionRow.amount < 0, -TransactionRow.amount), else_=0)), 0
    )
    stmt = (
        select(
            TransactionRow.category_id,
            Category.name.label("category_name"),
            money_out_expr.label("money_out"),
            money_in_expr.label("money_in"),
            func.count().label("count"),
        )
        .outerjoin(Category, TransactionRow.category_id == Category.id)
        .group_by(TransactionRow.category_id, Category.name)
        .order_by(money_out_expr.desc())
    )
    if date_from is not None:
        stmt = stmt.where(TransactionRow.posted_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(TransactionRow.posted_date <= date_to)
    if account_id is not None:
        stmt = stmt.where(TransactionRow.account_id == account_id)

    rows = session.execute(stmt).mappings().all()
    return [
        CategorySummaryRow(
            category_id=row["category_id"],
            category_name=row["category_name"],
            money_out=row["money_out"],
            money_in=row["money_in"],
            count=row["count"],
        )
        for row in rows
    ]


# --- Uploads (async upload queue; see finagent.worker) ---


def create_upload(
    session: Session,
    *,
    filename: str,
    file_sha256: str,
    media_type: str | None,
    data: bytes,
) -> Upload:
    """Queue one uploaded file for extraction.

    A re-upload of bytes already on record (by sha256, in ``statements``) is
    free: the upload is created already ``DONE`` and linked to the existing
    statement, with ``data`` never stored, so it never reaches the worker or
    costs a model call. Otherwise it's queued for the worker to pick up.
    """
    existing_statement = get_statement_by_sha256(session, file_sha256)
    if existing_statement is not None:
        upload = Upload(
            filename=filename,
            file_sha256=file_sha256,
            media_type=media_type,
            size_bytes=len(data),
            data=None,
            status="DONE",
            statement_id=existing_statement.id,
        )
    else:
        upload = Upload(
            filename=filename,
            file_sha256=file_sha256,
            media_type=media_type,
            size_bytes=len(data),
            data=data,
            status="QUEUED",
        )
    session.add(upload)
    session.flush()
    return upload


def claim_next_upload(session: Session) -> Upload | None:
    """Atomically claim the oldest queued upload for processing.

    ``FOR UPDATE SKIP LOCKED`` lets multiple worker processes claim
    different rows concurrently without blocking on each other.
    """
    stmt = (
        select(Upload)
        .where(Upload.status == "QUEUED")
        .order_by(Upload.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    upload = session.execute(stmt).scalar_one_or_none()
    if upload is None:
        return None
    upload.status = "PROCESSING"
    upload.updated_at = datetime.now(timezone.utc)
    session.flush()
    return upload


def complete_upload(session: Session, upload_id: int, statement_id: int) -> None:
    """Mark an upload DONE and drop its raw bytes."""
    upload = session.get(Upload, upload_id)
    if upload is None:
        return
    upload.status = "DONE"
    upload.statement_id = statement_id
    upload.data = None
    upload.updated_at = datetime.now(timezone.utc)


def fail_upload(session: Session, upload_id: int, error: str) -> None:
    """Mark an upload ERROR with a safe message, and drop its raw bytes."""
    upload = session.get(Upload, upload_id)
    if upload is None:
        return
    upload.status = "ERROR"
    upload.error = error
    upload.data = None
    upload.updated_at = datetime.now(timezone.utc)


def requeue_stale_processing(session: Session, older_than: timedelta) -> int:
    """Requeue PROCESSING uploads whose ``updated_at`` predates the cutoff.

    Recovers uploads orphaned by a worker crash or restart mid-processing.
    Returns the number of rows requeued.
    """
    cutoff = datetime.now(timezone.utc) - older_than
    stmt = select(Upload).where(Upload.status == "PROCESSING", Upload.updated_at < cutoff)
    stale = list(session.execute(stmt).scalars().all())
    for upload in stale:
        upload.status = "QUEUED"
        upload.updated_at = datetime.now(timezone.utc)
    session.flush()
    return len(stale)


def list_uncategorized_transaction_ids_for_statement(
    session: Session, statement_id: int
) -> list[int]:
    """The ids of one statement's freshly inserted, not-yet-categorized transactions."""
    stmt = select(TransactionRow.id).where(
        TransactionRow.statement_id == statement_id, TransactionRow.category_id.is_(None)
    )
    return list(session.execute(stmt).scalars().all())


def get_upload(session: Session, upload_id: int) -> Upload | None:
    """Look up an upload by id."""
    return session.get(Upload, upload_id)


def list_uploads(session: Session, *, limit: int = 50, offset: int = 0) -> list[Upload]:
    """List uploads, newest first."""
    stmt = select(Upload).order_by(Upload.id.desc()).limit(limit).offset(offset)
    return list(session.execute(stmt).scalars().all())
