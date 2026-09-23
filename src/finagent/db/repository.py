"""Idempotent persistence of an ``ExtractionResult`` (AGENTS.md §3: dedup).

``save_extraction`` is the single entry point: it upserts the account,
records the statement (whatever its status), and -- for VERIFIED/UNVERIFIED
statements only -- inserts transactions with hash-based dedup. Everything
happens in one transaction; the caller owns commit.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from finagent.db.models import Account, Statement
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
    existing = session.execute(
        select(Statement).where(Statement.file_sha256 == file_sha256)
    ).scalar_one_or_none()
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
