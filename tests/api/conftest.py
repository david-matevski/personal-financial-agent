"""Shared fixtures for tests/api.

DB-backed tests reuse the session-scoped Postgres fixtures from
tests/conftest.py (``db_engine``, ``session``); they skip automatically when
Postgres isn't reachable. Tests that never reach the database (auth,
upload-size validation) don't depend on ``session`` at all.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from finagent.api.app import create_app
from finagent.api.deps import get_db
from finagent.core.config import Settings, get_settings

API_TOKEN = "test-token"


@pytest.fixture
def api_settings() -> Settings:
    return Settings(_env_file=None, api_token=API_TOKEN)  # type: ignore[call-arg]


@pytest.fixture
def client(session: Session, api_settings: Settings) -> Iterator[TestClient]:
    """A TestClient wired to the real (migrated, truncated-after) test DB.

    ``get_extractor`` is deliberately left un-overridden here: individual
    tests set ``client.app.dependency_overrides[get_extractor]`` to a
    ``FakeExtractor`` with the results/error they need.
    """
    app = create_app()

    def override_get_db() -> Iterator[Session]:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = lambda: api_settings

    with TestClient(app) as test_client:
        test_client.headers.update({"Authorization": f"Bearer {API_TOKEN}"})
        yield test_client

    app.dependency_overrides.clear()
