"""Tests for the static UI mount and GET /api-info (no DB needed)."""

import importlib.resources

import pytest
from fastapi.testclient import TestClient

from finagent import __version__
from finagent.api.app import create_app


def test_api_info_requires_no_auth() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/api-info")

    assert response.status_code == 200
    assert response.json() == {"name": "finagent", "version": __version__}


def test_static_root_serves_index_html_when_static_dir_exists() -> None:
    static_dir = importlib.resources.files("finagent") / "web" / "static"
    if not static_dir.is_dir():
        pytest.skip("web/static not present")

    with TestClient(create_app()) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    # No build step means unchanged file names across releases; browsers
    # must revalidate or they keep running stale JS after a redeploy.
    assert response.headers["cache-control"] == "no-cache"


def test_api_routes_win_over_the_static_mount() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
