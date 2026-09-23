"""DB-backed tests for POST/GET /uploads (skip if Postgres is unreachable)."""

from fastapi.testclient import TestClient

from finagent.api.deps import get_extractor
from tests.api.helpers import FakeExtractor, make_extraction

_CSV_BYTES = b"whatever, the fake extractor ignores this"


def test_upload_new_file_is_queued(client: TestClient) -> None:
    response = client.post("/uploads", files={"file": ("statement.csv", _CSV_BYTES, "text/csv")})

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "QUEUED"
    assert body["filename"] == "statement.csv"
    assert body["size_bytes"] == len(_CSV_BYTES)
    assert body["statement_id"] is None
    assert body["statement_status"] is None
    assert body["transactions_inserted"] is None
    assert body["error"] is None


def test_reupload_same_bytes_is_immediately_done(client: TestClient) -> None:
    extractor = FakeExtractor([make_extraction()])
    client.app.dependency_overrides[get_extractor] = lambda: extractor
    first_upload = client.post(
        "/statements", files={"file": ("statement.csv", _CSV_BYTES, "text/csv")}
    )
    assert first_upload.status_code == 201

    response = client.post("/uploads", files={"file": ("statement.csv", _CSV_BYTES, "text/csv")})

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "DONE"
    assert body["statement_id"] == first_upload.json()["statement_id"]
    assert body["statement_status"] is not None


def test_empty_file_returns_400(client: TestClient) -> None:
    response = client.post("/uploads", files={"file": ("empty.csv", b"", "text/csv")})

    assert response.status_code == 400


def test_get_upload_not_found_returns_404(client: TestClient) -> None:
    response = client.get("/uploads/999999")

    assert response.status_code == 404


def test_get_upload_by_id(client: TestClient) -> None:
    created = client.post("/uploads", files={"file": ("a.csv", _CSV_BYTES, "text/csv")})
    upload_id = created.json()["id"]

    response = client.get(f"/uploads/{upload_id}")

    assert response.status_code == 200
    assert response.json()["id"] == upload_id


def test_list_uploads_is_newest_first(client: TestClient) -> None:
    client.post("/uploads", files={"file": ("one.csv", _CSV_BYTES, "text/csv")})
    second = client.post("/uploads", files={"file": ("two.csv", _CSV_BYTES + b"x", "text/csv")})

    response = client.get("/uploads")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["id"] == second.json()["id"]


def test_uploads_requires_auth(client: TestClient) -> None:
    del client.headers["Authorization"]

    response = client.post("/uploads", files={"file": ("a.csv", _CSV_BYTES, "text/csv")})

    assert response.status_code == 401
