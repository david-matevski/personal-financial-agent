"""DB-backed tests for GET /categories and GET /categories/summary (skip if no Postgres)."""

from decimal import Decimal

from fastapi.testclient import TestClient

from finagent.api.deps import get_categorizer, get_extractor
from tests.api.helpers import FakeExtractor, make_extraction
from tests.categorize.helpers import FakeCategorizer


def test_list_categories_returns_seeded_rows(client: TestClient) -> None:
    response = client.get("/categories")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 15
    assert all("id" in row and "name" in row and "description" in row for row in body)
    assert all(row["description"] for row in body)


def test_summary_includes_uncategorized_group_and_correct_sums(client: TestClient) -> None:
    extractor = FakeExtractor(
        [
            make_extraction(
                closing_balance="97.00",
                transactions=[
                    {
                        "posted_date": "2026-01-05",
                        "description": "Fictional Coffee Co",
                        "amount": "5.00",
                        "direction": "OUT",
                    },
                    {
                        "posted_date": "2026-01-10",
                        "description": "Refund",
                        "amount": "8.00",
                        "direction": "IN",
                    },
                ],
            )
        ]
    )
    client.app.dependency_overrides[get_extractor] = lambda: extractor
    response = client.post("/statements", files={"file": ("a.csv", b"a.csv", "text/csv")})
    assert response.status_code == 201, response.text

    response = client.get("/categories/summary")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    row = body[0]
    assert row["category_id"] is None
    assert row["category_name"] is None
    assert isinstance(row["money_out"], str)
    assert isinstance(row["money_in"], str)
    assert Decimal(row["money_out"]) == Decimal("5.00")
    assert Decimal(row["money_in"]) == Decimal("8.00")
    assert row["count"] == 2


def test_summary_splits_by_category_after_categorization(client: TestClient) -> None:
    extractor = FakeExtractor([make_extraction()])
    client.app.dependency_overrides[get_extractor] = lambda: extractor
    response = client.post("/statements", files={"file": ("a.csv", b"a.csv", "text/csv")})
    assert response.status_code == 201, response.text

    client.app.dependency_overrides[get_categorizer] = lambda: FakeCategorizer()
    categorize_response = client.post("/transactions/categorize")
    assert categorize_response.status_code == 200, categorize_response.text

    response = client.get("/categories/summary")

    body = response.json()
    assert len(body) == 1
    assert body[0]["category_id"] is not None
    assert Decimal(body[0]["money_out"]) == Decimal("5.00")
    assert Decimal(body[0]["money_in"]) == Decimal("0")
