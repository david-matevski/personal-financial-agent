"""Upload validation tests (no DB): empty file -> 400, oversize -> 413.

``max_upload_bytes`` is overridden to a tiny value so the oversize case
doesn't need a real 20MB payload. Both checks happen before the sha256
lookup or the extractor is touched, so no database is needed here either.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from finagent.api.app import create_app
from finagent.api.deps import get_extractor
from finagent.core.config import Settings, get_settings
from finagent.ingest.document import SourceDocument
from finagent.ingest.extract.schema import StatementExtraction

_MAX_UPLOAD_BYTES = 16


class _UnusedExtractor:
    """Fails the test loudly if extraction is ever reached."""

    def extract(self, doc: SourceDocument, feedback: str | None = None) -> StatementExtraction:
        raise AssertionError("extractor should not be called for a rejected upload")


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app()
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        api_token="test-token",
        max_upload_bytes=_MAX_UPLOAD_BYTES,
    )
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_extractor] = lambda: _UnusedExtractor()

    with TestClient(app) as test_client:
        test_client.headers.update({"Authorization": "Bearer test-token"})
        yield test_client

    app.dependency_overrides.clear()


def test_empty_file_returns_400(client: TestClient) -> None:
    response = client.post("/statements", files={"file": ("empty.csv", b"", "text/csv")})

    assert response.status_code == 400


def test_oversize_file_returns_413(client: TestClient) -> None:
    oversize = b"x" * (_MAX_UPLOAD_BYTES + 1)

    response = client.post("/statements", files={"file": ("big.csv", oversize, "text/csv")})

    assert response.status_code == 413
