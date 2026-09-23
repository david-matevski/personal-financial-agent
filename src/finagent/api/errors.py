"""Maps domain exceptions (core/errors.py) to HTTP responses.

The single place that translates ``FinAgentError`` subclasses into status
codes, so routes never need their own try/except (AGENTS.md §3: "no
business logic in routes"). A ``FAILED`` extraction is not an error -- it's
a successful 201 response with ``status=FAILED``; only genuine failures to
load/extract a document land here.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

from finagent.core.errors import ExtractionError, ParseError, UnsupportedStatementError

logger = logging.getLogger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    """Attach the domain-exception -> HTTP-response mapping to ``app``."""
    app.add_exception_handler(UnsupportedStatementError, _handle_unsupported)
    app.add_exception_handler(ParseError, _handle_parse_error)
    app.add_exception_handler(ExtractionError, _handle_extraction_error)
    app.add_exception_handler(OperationalError, _handle_database_unavailable)


def _handle_unsupported(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=415, content={"detail": str(exc)})


def _handle_parse_error(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})


def _handle_extraction_error(request: Request, exc: Exception) -> JSONResponse:
    # Never echo the exception's own message: it can originate from
    # document content (AGENTS.md §3: never log/return raw statement text).
    logger.warning("statement extraction failed: %s", type(exc).__name__)
    return JSONResponse(status_code=502, content={"detail": "Statement extraction failed"})


def _handle_database_unavailable(request: Request, exc: Exception) -> JSONResponse:
    # Connection-level failures (DB down, bad credentials, timeout). The
    # driver message can include host/user details, so return a fixed one.
    logger.error("database unavailable: %s", type(exc).__name__)
    return JSONResponse(status_code=503, content={"detail": "Database unavailable"})
