"""FastAPI dependencies: DB session, auth, and the extractor.

Kept separate from routes so business logic never lives in the route
functions themselves (AGENTS.md §3), and so tests can override each of
these independently (fake extractor, lowered upload-size limit, ...).
"""

import secrets
from collections.abc import Iterator

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from finagent.core.config import Settings, build_extractor, get_settings
from finagent.db.session import session_scope
from finagent.ingest.extract.base import StatementExtractor


def get_db() -> Iterator[Session]:
    """Yield one session per request; commit on success, roll back on exception."""
    with session_scope() as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise


def get_extractor(settings: Settings = Depends(get_settings)) -> StatementExtractor:
    """The extractor used by the upload route. Overridden with a fake in tests."""
    return build_extractor(settings)


def require_auth(request: Request, settings: Settings = Depends(get_settings)) -> None:
    """Bearer-token auth, applied at router level to every protected router.

    Fails closed: an unconfigured token (``settings.api_token is None``)
    refuses every protected request with 503 rather than letting them
    through, since this API serves financial data.
    """
    if settings.api_token is None:
        raise HTTPException(status_code=503, detail="API token not configured")

    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    # Compare bytes: str compare_digest raises TypeError on non-ASCII input,
    # which would turn a bad header into a 500 instead of a 401.
    valid = scheme.lower() == "bearer" and secrets.compare_digest(
        token.encode(), settings.api_token.get_secret_value().encode()
    )
    if not valid:
        raise HTTPException(status_code=401, detail="Invalid or missing bearer token")
