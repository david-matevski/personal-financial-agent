"""Tests for the static UI mount and GET /api-info (no DB needed)."""

import importlib.resources
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from finagent import __version__
from finagent.api.app import create_app
from finagent.core.static_assets import compute_build_id, rewrite_index_html

BUILD_ID_RE = re.compile(r"/static/([0-9a-f]{12})/app\.js")


def test_api_info_requires_no_auth() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/api-info")

    assert response.status_code == 200
    assert response.json() == {"name": "finagent", "version": __version__}


def _static_dir_or_skip() -> Path:
    static_dir = importlib.resources.files("finagent") / "web" / "static"
    if not static_dir.is_dir():
        pytest.skip("web/static not present")
    return Path(str(static_dir))


def test_static_root_serves_versioned_index_html_when_static_dir_exists() -> None:
    _static_dir_or_skip()

    with TestClient(create_app()) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    # A stale index.html could point at assets from a different, incompatible
    # build; no-store means the browser always fetches a fresh one that
    # names the build id currently being served.
    assert response.headers["cache-control"] == "no-store"

    body = response.text
    match = BUILD_ID_RE.search(body)
    assert match is not None, body
    build_id = match.group(1)
    assert f'href="/static/{build_id}/app.css"' in body
    assert 'src="app.js"' not in body
    assert 'href="app.css"' not in body


def test_static_assets_are_served_under_the_build_id_with_immutable_caching() -> None:
    static_path = _static_dir_or_skip()
    build_id = compute_build_id(static_path)

    with TestClient(create_app()) as client:
        app_js_response = client.get(f"/static/{build_id}/app.js")
        nested_response = client.get(f"/static/{build_id}/js/views/spending.js")

    for response in (app_js_response, nested_response):
        assert response.status_code == 200
        assert response.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_static_assets_404_under_the_wrong_build_id() -> None:
    _static_dir_or_skip()

    with TestClient(create_app()) as client:
        response = client.get("/static/000000000000/app.js")

    assert response.status_code == 404


def test_api_routes_win_over_the_static_mount() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_build_id_changes_when_a_file_changes(tmp_path: Path) -> None:
    (tmp_path / "app.js").write_bytes(b"console.log('v1');")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "helper.js").write_bytes(b"export const x = 1;")

    original = compute_build_id(tmp_path)
    # Same content, recomputed, is stable.
    assert compute_build_id(tmp_path) == original

    (tmp_path / "sub" / "helper.js").write_bytes(b"export const x = 2;")
    assert compute_build_id(tmp_path) != original


def test_build_id_depends_on_file_paths_not_just_contents(tmp_path: Path) -> None:
    (tmp_path / "a.js").write_bytes(b"same")
    (tmp_path / "b.js").write_bytes(b"same")
    combined = compute_build_id(tmp_path)

    (tmp_path / "a.js").unlink()
    (tmp_path / "b.js").unlink()
    (tmp_path / "a.js").write_bytes(b"same")

    assert compute_build_id(tmp_path) != combined


def test_rewrite_index_html_replaces_css_and_js_references() -> None:
    html = '<link rel="stylesheet" href="app.css">\n<script type="module" src="app.js"></script>'

    rewritten = rewrite_index_html(html, "abcdef012345")

    assert 'href="/static/abcdef012345/app.css"' in rewritten
    assert 'src="/static/abcdef012345/app.js"' in rewritten


def test_rewrite_index_html_leaves_hash_nav_links_untouched() -> None:
    html = '<a href="#/upload">Upload</a><link href="app.css"><script src="app.js"></script>'

    rewritten = rewrite_index_html(html, "abcdef012345")

    assert '<a href="#/upload">Upload</a>' in rewritten


def test_rewrite_index_html_raises_when_a_reference_is_missing() -> None:
    html = '<script type="module" src="app.js"></script>'  # no app.css link

    with pytest.raises(ValueError, match=re.escape("app.css")):
        rewrite_index_html(html, "abcdef012345")


def test_rewrite_index_html_raises_when_a_reference_appears_twice() -> None:
    html = '<link href="app.css"><link href="app.css"><script src="app.js"></script>'

    with pytest.raises(ValueError, match=re.escape("app.css")):
        rewrite_index_html(html, "abcdef012345")
