"""POST /statements, GET /statements, GET /statements/{id}.

Route functions only wire request -> pipeline/repository -> response; the
actual work (hashing, extraction, persistence) lives in ``ingest.pipeline``
and ``db.repository``.
"""

import hashlib

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from sqlalchemy.orm import Session

from finagent.api.deps import get_db, get_extractor, require_auth
from finagent.api.schemas import StatementDetail, StatementSummary, UploadResponse
from finagent.core.config import Settings, get_settings
from finagent.db.models import Statement
from finagent.db.repository import (
    get_statement,
    get_statement_by_sha256,
    list_statements,
    save_extraction,
)
from finagent.ingest.extract.base import StatementExtractor
from finagent.ingest.pipeline import extract_statement

router = APIRouter(tags=["statements"], dependencies=[Depends(require_auth)])


# Defined as a sync `def`: FastAPI runs sync path functions in a worker
# threadpool automatically, which gets us the same "don't block the event
# loop" behaviour as an explicit `run_in_threadpool` call around
# `extract_statement` (which is synchronous: it calls the Anthropic SDK and
# SQLAlchemy, neither of which is async here) without the extra ceremony.
@router.post("/statements", response_model=UploadResponse, status_code=201)
def upload_statement(
    response: Response,
    file: UploadFile = File(...),
    session: Session = Depends(get_db),
    extractor: StatementExtractor = Depends(get_extractor),
    settings: Settings = Depends(get_settings),
) -> UploadResponse:
    """Upload a statement file for extraction and persistence.

    Re-uploading bytes already on record (by sha256) is a no-op: it returns
    the existing statement with ``already_imported=True`` and never calls
    the extractor, so re-uploads don't cost API spend.
    """
    filename = file.filename or "upload"

    # Read at most one byte past the limit so an oversized upload doesn't
    # get pulled entirely into memory just to be rejected.
    data = file.file.read(settings.max_upload_bytes + 1)
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="File exceeds maximum upload size")

    file_sha256 = hashlib.sha256(data).hexdigest()

    existing = get_statement_by_sha256(session, file_sha256)
    if existing is not None:
        response.status_code = 200
        return UploadResponse(
            statement_id=existing.id,
            status=existing.status,
            attempts=existing.attempts,
            problems=list(existing.problems),
            transactions_inserted=existing.transactions_inserted,
            transactions_skipped_duplicate=0,
            already_imported=True,
        )

    # End the read-only transaction before the slow (30-90s) model call so
    # the pooled connection isn't held idle-in-transaction meanwhile.
    session.commit()
    result = extract_statement(filename, data, extractor)
    saved = save_extraction(
        session,
        filename=filename,
        file_sha256=file_sha256,
        media_type=file.content_type,
        result=result,
        extraction_json=result.extraction.model_dump(mode="json"),
        model=settings.extraction_model,
    )
    return UploadResponse(
        statement_id=saved.statement_id,
        status=saved.status.value,
        attempts=result.attempts,
        problems=list(result.problems),
        transactions_inserted=saved.transactions_inserted,
        transactions_skipped_duplicate=saved.transactions_skipped_duplicate,
        already_imported=saved.already_imported,
    )


@router.get("/statements", response_model=list[StatementSummary])
def list_statements_route(
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db),
) -> list[StatementSummary]:
    """List statements, newest first, optionally filtered by status."""
    rows = list_statements(session, status=status, limit=limit, offset=offset)
    return [_to_summary(row) for row in rows]


@router.get("/statements/{statement_id}", response_model=StatementDetail)
def get_statement_route(
    statement_id: int,
    include_extraction: bool = False,
    session: Session = Depends(get_db),
) -> StatementDetail:
    """Fetch one statement; pass ``include_extraction=true`` for the raw JSON."""
    row = get_statement(session, statement_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Statement not found")
    return _to_detail(row, include_extraction=include_extraction)


def _to_summary(row: Statement) -> StatementSummary:
    return StatementSummary(
        id=row.id,
        account_id=row.account_id,
        filename=row.filename,
        file_sha256=row.file_sha256,
        media_type=row.media_type,
        status=row.status,
        attempts=row.attempts,
        problems=list(row.problems),
        period_start=row.period_start,
        period_end=row.period_end,
        opening_balance=_str_or_none(row.opening_balance),
        closing_balance=_str_or_none(row.closing_balance),
        total_money_out=_str_or_none(row.total_money_out),
        total_money_in=_str_or_none(row.total_money_in),
        model=row.model,
        transactions_inserted=row.transactions_inserted,
        created_at=row.created_at,
    )


def _to_detail(row: Statement, *, include_extraction: bool) -> StatementDetail:
    summary = _to_summary(row)
    return StatementDetail(
        **summary.model_dump(),
        extraction=row.extraction if include_extraction else None,
    )


def _str_or_none(value: object) -> str | None:
    return None if value is None else str(value)
