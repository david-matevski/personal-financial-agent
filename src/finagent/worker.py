"""Background worker draining the async upload queue (see ``db.repository``).

The browser UI is reached through a tunnel that cuts off requests at
~100s, but extraction takes 30-90s. So ``POST /uploads`` returns
immediately (see ``api/routes/uploads.py``) and this worker does the slow
work out of band: claim a queued upload, run it through the same
load -> extract -> validate -> persist pipeline as the synchronous
``POST /statements`` endpoint, and record the outcome.
"""

import logging
import threading
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import timedelta

from sqlalchemy.orm import Session

from finagent.categorize.base import TransactionCategorizer
from finagent.categorize.service import categorize_transactions
from finagent.core.errors import CategorizationError, ExtractionError, FinAgentError
from finagent.db.repository import (
    claim_next_upload,
    complete_upload,
    fail_upload,
    list_uncategorized_transaction_ids_for_statement,
    requeue_stale_processing,
    save_extraction,
)
from finagent.ingest.extract.base import StatementExtractor
from finagent.ingest.pipeline import extract_statement

logger = logging.getLogger(__name__)

_NOT_CONFIGURED_MESSAGE = "Extraction is not configured (ANTHROPIC_API_KEY missing)"
_CATEGORIZE_LEFTOVER_LIMIT = 100


class UploadWorker:
    """Polls ``uploads`` for queued rows and processes them one at a time.

    ``session_factory`` yields a session per unit of work (e.g.
    ``db.session.session_scope``); ``extractor_factory`` builds a
    ``StatementExtractor`` on demand so a missing API key is discovered at
    process time, not at worker construction time.
    """

    def __init__(
        self,
        session_factory: Callable[[], AbstractContextManager[Session]],
        extractor_factory: Callable[[], StatementExtractor],
        categorizer_factory: Callable[[], TransactionCategorizer],
        model: str,
        poll_interval: float = 2.0,
        categorize_interval: float = 60.0,
    ) -> None:
        self._session_factory = session_factory
        self._extractor_factory = extractor_factory
        self._categorizer_factory = categorizer_factory
        self._model = model
        self._poll_interval = poll_interval
        self._categorize_interval = categorize_interval
        self._warned_not_configured = False
        self._last_categorize_sweep = 0.0

    def process_one(self) -> bool:
        """Claim and process one queued upload. Returns False if none was queued."""
        claimed = self._claim()
        if claimed is None:
            return False
        upload_id, filename, data, media_type, file_sha256 = claimed

        try:
            extractor = self._extractor_factory()
        except ExtractionError:
            if not self._warned_not_configured:
                logger.warning("upload worker: %s", _NOT_CONFIGURED_MESSAGE)
                self._warned_not_configured = True
            self._fail(upload_id, _NOT_CONFIGURED_MESSAGE)
            return True

        try:
            self._extract_and_save(
                upload_id,
                filename=filename,
                data=data,
                media_type=media_type,
                file_sha256=file_sha256,
                extractor=extractor,
            )
        except FinAgentError as exc:
            self._fail(upload_id, str(exc))
        except Exception as exc:
            # Never let an unexpected exception surface upload content or
            # crash the worker thread. Log the type only: messages and
            # tracebacks (e.g. pydantic validation errors) can embed
            # extracted statement data (AGENTS.md §3).
            logger.error(
                "upload worker: unexpected %s processing upload %s",
                type(exc).__name__,
                upload_id,
            )
            self._fail(upload_id, "internal error")
        return True

    def run(self, stop_event: threading.Event) -> None:
        """Poll until ``stop_event`` is set, sleeping between idle polls."""
        while not stop_event.is_set():
            try:
                processed = self.process_one()
            except Exception as exc:
                logger.error("upload worker: unexpected %s in poll loop", type(exc).__name__)
                processed = False
            if not processed:
                self._maybe_categorize_leftovers()
                stop_event.wait(self._poll_interval)

    def _claim(self) -> tuple[int, str, bytes, str | None, str] | None:
        with self._session_factory() as session:
            upload = claim_next_upload(session)
            if upload is None:
                session.rollback()
                return None
            claimed = (
                upload.id,
                upload.filename,
                upload.data or b"",
                upload.media_type,
                upload.file_sha256,
            )
            # Commit now (not held across the 30-90s extraction call below)
            # so the pooled connection isn't idle-in-transaction meanwhile,
            # matching the pattern in api/routes/statements.py.
            session.commit()
            return claimed

    def _extract_and_save(
        self,
        upload_id: int,
        *,
        filename: str,
        data: bytes,
        media_type: str | None,
        file_sha256: str,
        extractor: StatementExtractor,
    ) -> None:
        result = extract_statement(filename, data, extractor)
        with self._session_factory() as session:
            saved = save_extraction(
                session,
                filename=filename,
                file_sha256=file_sha256,
                media_type=media_type,
                result=result,
                extraction_json=result.extraction.model_dump(mode="json"),
                model=self._model,
            )
            complete_upload(session, upload_id, saved.statement_id)
            session.commit()
            statement_id = saved.statement_id

        # In its own DB transaction/session, deliberately after the upload's
        # own commit above: a categorization failure (or a missing API key)
        # must never fail the upload itself -- it just leaves the new
        # transactions uncategorized for the idle sweep (or a manual
        # POST /transactions/categorize) to pick up later.
        self._categorize_after_upload(statement_id)

    def _categorize_after_upload(self, statement_id: int) -> None:
        try:
            categorizer = self._categorizer_factory()
            with self._session_factory() as session:
                transaction_ids = list_uncategorized_transaction_ids_for_statement(
                    session, statement_id
                )
                if not transaction_ids:
                    session.rollback()
                    return
                categorize_transactions(
                    session,
                    categorizer,
                    transaction_ids=transaction_ids,
                    limit=len(transaction_ids),
                )
                session.commit()
        except CategorizationError:
            # Never surfaced to the upload: exception type only, never the
            # message, since it could echo document content (AGENTS.md §3).
            logger.warning(
                "upload worker: %s categorizing statement %s",
                CategorizationError.__name__,
                statement_id,
            )
        except Exception as exc:
            logger.error(
                "upload worker: unexpected %s categorizing statement %s",
                type(exc).__name__,
                statement_id,
            )

    def _maybe_categorize_leftovers(self) -> None:
        """Self-heals rows left uncategorized by an earlier failed attempt.

        Runs at most once every ``self._categorize_interval`` seconds, only
        when the upload queue is idle, so it never competes with real
        upload processing for the categorizer or the DB.
        """
        now = time.monotonic()
        if now - self._last_categorize_sweep < self._categorize_interval:
            return
        self._last_categorize_sweep = now
        try:
            categorizer = self._categorizer_factory()
            with self._session_factory() as session:
                categorize_transactions(session, categorizer, limit=_CATEGORIZE_LEFTOVER_LIMIT)
                session.commit()
        except CategorizationError:
            logger.warning(
                "upload worker: %s during idle categorization sweep", CategorizationError.__name__
            )
        except Exception as exc:
            logger.error(
                "upload worker: unexpected %s during idle categorization sweep", type(exc).__name__
            )

    def _fail(self, upload_id: int, message: str) -> None:
        with self._session_factory() as session:
            fail_upload(session, upload_id, message)
            session.commit()


def requeue_stale(session_factory: Callable[[], AbstractContextManager[Session]]) -> int:
    """Requeue uploads stuck PROCESSING for >10 minutes, e.g. after a crash.

    Run once at worker start.
    """
    with session_factory() as session:
        count = requeue_stale_processing(session, timedelta(minutes=10))
        session.commit()
        return count
