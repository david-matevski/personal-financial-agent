"""Tests for the GET /health endpoint."""

from fastapi.testclient import TestClient

from finagent import __version__
from finagent.api.app import create_app


def test_health_returns_ok_status_and_version() -> None:
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}
