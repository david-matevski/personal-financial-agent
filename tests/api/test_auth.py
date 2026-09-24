"""Auth tests for the bearer-token dependency (no DB needed)."""

from collections.abc import Iterator
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from finagent.api.app import create_app
from finagent.api.deps import get_db
from finagent.core.config import Settings, get_settings


def _stub_db() -> Iterator[MagicMock]:
    yield MagicMock()


def _client(settings: Settings) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app, raise_server_exceptions=False)


def test_health_is_open_with_no_token_configured() -> None:
    client = _client(Settings(_env_file=None, api_token=None))  # type: ignore[call-arg]

    response = client.get("/health")

    assert response.status_code == 200


def test_health_is_open_even_with_a_token_and_no_header() -> None:
    client = _client(Settings(_env_file=None, api_token="secret"))  # type: ignore[call-arg]

    response = client.get("/health")

    assert response.status_code == 200


def test_protected_endpoint_returns_503_when_no_token_configured() -> None:
    client = _client(Settings(_env_file=None, api_token=None))  # type: ignore[call-arg]

    response = client.get("/accounts")

    assert response.status_code == 503


def test_protected_endpoint_returns_401_when_authorization_header_missing() -> None:
    client = _client(Settings(_env_file=None, api_token="secret"))  # type: ignore[call-arg]

    response = client.get("/accounts")

    assert response.status_code == 401


def test_protected_endpoint_returns_401_for_wrong_token() -> None:
    client = _client(Settings(_env_file=None, api_token="secret"))  # type: ignore[call-arg]

    response = client.get("/accounts", headers={"Authorization": "Bearer wrong"})

    assert response.status_code == 401


def test_protected_endpoint_returns_401_for_non_bearer_scheme() -> None:
    client = _client(Settings(_env_file=None, api_token="secret"))  # type: ignore[call-arg]

    response = client.get("/accounts", headers={"Authorization": "Basic secret"})

    assert response.status_code == 401


def test_protected_endpoint_with_correct_token_passes_auth() -> None:
    client = _client(Settings(_env_file=None, api_token="secret"))  # type: ignore[call-arg]
    # Stub session: this test is about auth, and must never open a real DB
    # connection (with no Postgres reachable that would block, not fail).
    client.app.dependency_overrides[get_db] = _stub_db  # type: ignore[attr-defined]

    response = client.get("/accounts", headers={"Authorization": "Bearer secret"})

    assert response.status_code == 200


def test_non_ascii_bearer_token_is_rejected_not_a_server_error() -> None:
    client = _client(Settings(_env_file=None, api_token="secret"))  # type: ignore[call-arg]

    response = client.get("/accounts", headers={"Authorization": "Bearer sécret".encode()})

    assert response.status_code == 401


def test_database_outage_returns_503_with_a_safe_message() -> None:
    client = _client(Settings(_env_file=None, api_token="secret"))  # type: ignore[call-arg]
    client.app.dependency_overrides[get_db] = _unreachable_db  # type: ignore[attr-defined]

    response = client.get("/accounts", headers={"Authorization": "Bearer secret"})

    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}


def _unreachable_db() -> Iterator[MagicMock]:
    session = MagicMock()
    session.execute.side_effect = OperationalError("SELECT 1", {}, Exception("connection refused"))
    yield session
