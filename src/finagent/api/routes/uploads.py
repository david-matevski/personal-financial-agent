"""POST /uploads, GET /uploads, GET /uploads/{id}.

Unlike ``POST /statements`` (synchronous, for scripts), these endpoints
queue the file and return immediately: the browser UI is reached through a
tunnel that cuts requests off at ~100s, and extraction takes 30-90s. The
``finagent.worker.UploadWorker`` background thread drains the queue; these
routes only validate the upload and read/write ``uploads`` rows.
"""

import hashlib

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from finagent.api.deps import get_db, require_auth
from finagent.api.schemas import UploadOut
from finagent.core.config import Settings, get_settings
from finagent.db.models import Upload
from finagent.db.repository import create_upload, get_upload, list_uploads

router = APIRouter(tags=["uploads"], dependencies=[Depends(require_auth)])


@router.post("/uploads", response_model=UploadOut, status_code=202)
def create_upload_route(
    file: UploadFile = File(...),
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> UploadOut:
    """Queue one statement file for background extraction.

    Returns immediately with ``status=QUEUED`` (or ``DONE`` if this exact
    file is already on record). Send one file per request; the UI issues
    several requests in parallel for a multi-file drop.
    """
    filename = file.filename or "upload"

    # Same size/empty checks as POST /statements: read at most one byte
    # past the limit so an oversized upload isn't pulled fully into memory.
    data = file.file.read(settings.max_upload_bytes + 1)
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="File exceeds maximum upload size")

    file_sha256 = hashlib.sha256(data).hexdigest()
    upload = create_upload(
        session,
        filename=filename,
        file_sha256=file_sha256,
        media_type=file.content_type,
        data=data,
    )
    return _to_out(upload)


@router.get("/uploads", response_model=list[UploadOut])
def list_uploads_route(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db),
) -> list[UploadOut]:
    """List uploads, newest first."""
    rows = list_uploads(session, limit=limit, offset=offset)
    return [_to_out(row) for row in rows]


@router.get("/uploads/{upload_id}", response_model=UploadOut)
def get_upload_route(upload_id: int, session: Session = Depends(get_db)) -> UploadOut:
    """Fetch one upload's status, for the UI to poll."""
    row = get_upload(session, upload_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Upload not found")
    return _to_out(row)


def _to_out(row: Upload) -> UploadOut:
    statement = row.statement
    return UploadOut(
        id=row.id,
        filename=row.filename,
        size_bytes=row.size_bytes,
        status=row.status,
        error=row.error,
        statement_id=row.statement_id,
        statement_status=statement.status if statement is not None else None,
        transactions_inserted=statement.transactions_inserted if statement is not None else None,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
