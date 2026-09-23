"""DB-backed test for GET /categories (skip if no Postgres)."""

from fastapi.testclient import TestClient


def test_list_categories_returns_seeded_rows(client: TestClient) -> None:
    response = client.get("/categories")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 14
    assert all("id" in row and "name" in row for row in body)
