"""Unit tests for finagent.worker.UploadWorker.

Uses the real Postgres fixtures from tests/conftest.py (skips if
unreachable) plus a fake extractor -- no test ever calls the real Anthropic
API (AGENTS.md §3).
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from finagent.core.errors import CategorizationError, ExtractionError
from finagent.db.models import Transaction, Upload
from finagent.db.repository import claim_next_upload, create_upload, requeue_stale_processing
from finagent.worker import UploadWorker
from tests.api.helpers import FakeExtractor, make_extraction
from tests.categorize.helpers import FakeCategorizer


@contextmanager
def _session_factory(session: Session) -> Iterator[Session]:
    """Adapt the test's already-open session to UploadWorker's factory contract."""
    yield session


def _worker(
    session: Session,
    extractor_factory,  # type: ignore[no-untyped-def]
    categorizer_factory=lambda: FakeCategorizer(),  # type: ignore[no-untyped-def]
    model: str = "claude-test",
) -> UploadWorker:
    return UploadWorker(
        lambda: _session_factory(session), extractor_factory, categorizer_factory, model=model
    )


def test_process_one_returns_false_when_queue_is_empty(session: Session) -> None:
    worker = _worker(session, lambda: FakeExtractor([make_extraction()]))

    assert worker.process_one() is False


def test_process_one_extracts_and_links_statement(session: Session) -> None:
    upload = create_upload(
        session, filename="a.csv", file_sha256="a" * 64, media_type="text/csv", data=b"whatever"
    )
    session.commit()
    extractor = FakeExtractor([make_extraction()])
    worker = _worker(session, lambda: extractor)

    assert worker.process_one() is True

    session.expire_all()
    row = session.get(Upload, upload.id)
    assert row is not None
    assert row.status == "DONE"
    assert row.statement_id is not None
    assert row.data is None
    assert len(extractor.calls) == 1


def test_reupload_same_bytes_completes_without_calling_extractor(session: Session) -> None:
    create_upload(
        session, filename="a.csv", file_sha256="b" * 64, media_type="text/csv", data=b"data1"
    )
    session.commit()
    extractor = FakeExtractor([make_extraction()])
    worker = _worker(session, lambda: extractor)
    assert worker.process_one() is True  # processes the first upload

    reupload = create_upload(
        session, filename="a.csv", file_sha256="b" * 64, media_type="text/csv", data=b"data1"
    )
    session.commit()

    assert reupload.status == "DONE"
    assert reupload.statement_id is not None
    assert reupload.data is None
    assert len(extractor.calls) == 1  # never called again for the re-upload
    assert worker.process_one() is False  # nothing left queued


def test_extraction_error_marks_upload_error_with_message(session: Session) -> None:
    upload = create_upload(
        session, filename="a.csv", file_sha256="c" * 64, media_type="text/csv", data=b"bad"
    )
    session.commit()
    extractor = FakeExtractor(error=ExtractionError("printed totals didn't reconcile"))
    worker = _worker(session, lambda: extractor)

    assert worker.process_one() is True

    session.expire_all()
    row = session.get(Upload, upload.id)
    assert row is not None
    assert row.status == "ERROR"
    assert row.error == "printed totals didn't reconcile"
    assert row.data is None


def test_unexpected_error_marks_upload_with_generic_message(session: Session) -> None:
    upload = create_upload(
        session, filename="a.csv", file_sha256="i" * 64, media_type="text/csv", data=b"bad"
    )
    session.commit()
    extractor = FakeExtractor(error=RuntimeError("some internal detail"))
    worker = _worker(session, lambda: extractor)

    assert worker.process_one() is True

    session.expire_all()
    row = session.get(Upload, upload.id)
    assert row is not None
    assert row.status == "ERROR"
    assert row.error == "internal error"


def test_missing_extractor_configuration_fails_upload_with_safe_message(session: Session) -> None:
    upload = create_upload(
        session, filename="a.csv", file_sha256="d" * 64, media_type="text/csv", data=b"x"
    )
    session.commit()

    def _raise() -> FakeExtractor:
        raise ExtractionError("ANTHROPIC_API_KEY is not set; ...")

    worker = _worker(session, _raise)

    assert worker.process_one() is True

    session.expire_all()
    row = session.get(Upload, upload.id)
    assert row is not None
    assert row.status == "ERROR"
    assert row.error == "Extraction is not configured (ANTHROPIC_API_KEY missing)"


def test_categorizer_failure_after_upload_still_yields_done(session: Session) -> None:
    upload = create_upload(
        session, filename="a.csv", file_sha256="h" * 64, media_type="text/csv", data=b"whatever"
    )
    session.commit()
    extractor = FakeExtractor([make_extraction()])

    def _raise() -> FakeCategorizer:
        raise CategorizationError("ANTHROPIC_API_KEY is not set")

    worker = _worker(session, lambda: extractor, categorizer_factory=_raise)

    assert worker.process_one() is True

    session.expire_all()
    row = session.get(Upload, upload.id)
    assert row is not None
    assert row.status == "DONE"  # the upload succeeds even though categorization couldn't run
    assert row.statement_id is not None

    transactions = list(
        session.execute(
            select(Transaction).where(Transaction.statement_id == row.statement_id)
        ).scalars()
    )
    assert len(transactions) == 1
    assert transactions[0].category_id is None  # left uncategorized for a later retry


def test_requeue_stale_processing_recovers_orphaned_upload(session: Session) -> None:
    create_upload(session, filename="a.csv", file_sha256="e" * 64, media_type="text/csv", data=b"x")
    session.commit()
    claimed = claim_next_upload(session)
    session.commit()
    assert claimed is not None
    session.execute(
        text("UPDATE uploads SET updated_at = now() - interval '11 minutes' WHERE id = :id"),
        {"id": claimed.id},
    )
    session.commit()

    count = requeue_stale_processing(session, timedelta(minutes=10))
    session.commit()

    assert count == 1
    session.expire_all()
    row = session.get(Upload, claimed.id)
    assert row is not None
    assert row.status == "QUEUED"


def test_requeue_stale_processing_ignores_recent_rows(session: Session) -> None:
    create_upload(session, filename="a.csv", file_sha256="j" * 64, media_type="text/csv", data=b"x")
    session.commit()
    claim_next_upload(session)
    session.commit()

    count = requeue_stale_processing(session, timedelta(minutes=10))
    session.commit()

    assert count == 0


def test_claim_next_upload_sequential_calls_do_not_return_same_row(session: Session) -> None:
    create_upload(session, filename="a.csv", file_sha256="f" * 64, media_type="text/csv", data=b"x")
    create_upload(session, filename="b.csv", file_sha256="g" * 64, media_type="text/csv", data=b"y")
    session.commit()

    first = claim_next_upload(session)
    session.commit()
    second = claim_next_upload(session)
    session.commit()

    assert first is not None
    assert second is not None
    assert first.id != second.id
