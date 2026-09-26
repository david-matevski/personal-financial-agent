"""DB-backed tests for GET /transactions and GET /accounts (skip if no Postgres)."""

from decimal import Decimal

from fastapi.testclient import TestClient

from finagent.api.deps import get_categorizer, get_extractor
from finagent.core.errors import CategorizationError
from tests.api.helpers import FakeExtractor, make_extraction
from tests.categorize.helpers import FakeCategorizer


def _upload(
    client: TestClient, filename: str, extraction_overrides: dict[str, object]
) -> dict[str, object]:
    extractor = FakeExtractor([make_extraction(**extraction_overrides)])
    client.app.dependency_overrides[get_extractor] = lambda: extractor
    response = client.post("/statements", files={"file": (filename, filename.encode(), "text/csv")})
    assert response.status_code == 201, response.text
    body = response.json()
    # A reconciliation mismatch in the fixture would silently store no rows.
    assert body["status"] == "VERIFIED", body
    return body


def test_transaction_amounts_are_serialized_as_strings(client: TestClient) -> None:
    _upload(client, "a.csv", {})

    response = client.get("/transactions")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["amount"] == "5.00"
    assert isinstance(body[0]["amount"], str)


def test_transactions_filter_by_account_id(client: TestClient) -> None:
    _upload(client, "td.csv", {"issuer": "TD", "account_last4": "1234"})
    _upload(
        client,
        "amex.csv",
        {
            "issuer": "AMEX",
            "account_last4": "9999",
            "closing_balance": "108.00",
            "transactions": [
                {
                    "posted_date": "2026-01-06",
                    "description": "Fictional Grocer",
                    "amount": "8.00",
                    "direction": "OUT",
                }
            ],
        },
    )
    accounts = client.get("/accounts").json()
    assert len(accounts) == 2
    td_account = next(a for a in accounts if a["issuer"] == "TD")

    response = client.get("/transactions", params={"account_id": td_account["id"]})

    body = response.json()
    assert len(body) == 1
    assert body[0]["account_id"] == td_account["id"]


def test_transactions_filter_by_date_range(client: TestClient) -> None:
    _upload(
        client,
        "multi.csv",
        {
            "closing_balance": "113.00",
            "transactions": [
                {
                    "posted_date": "2026-01-05",
                    "description": "Fictional Coffee Co",
                    "amount": "5.00",
                    "direction": "OUT",
                },
                {
                    "posted_date": "2026-01-20",
                    "description": "Fictional Grocer",
                    "amount": "8.00",
                    "direction": "OUT",
                },
            ],
        },
    )

    response = client.get(
        "/transactions", params={"date_from": "2026-01-10", "date_to": "2026-01-31"}
    )

    body = response.json()
    assert len(body) == 1
    assert body[0]["description"] == "Fictional Grocer"


def test_transactions_limit_over_1000_is_rejected(client: TestClient) -> None:
    response = client.get("/transactions", params={"limit": 1001})

    assert response.status_code == 422


def test_patch_sets_user_category_source(client: TestClient) -> None:
    _upload(client, "a.csv", {})
    transaction_id = client.get("/transactions").json()[0]["id"]
    category_id = client.get("/categories").json()[0]["id"]

    response = client.patch(f"/transactions/{transaction_id}", json={"category_id": category_id})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["category_id"] == category_id
    assert body["category_source"] == "user"
    assert body["category_confidence"] is None
    assert body["needs_review"] is False


def test_patch_with_unknown_category_id_is_422(client: TestClient) -> None:
    _upload(client, "a.csv", {})
    transaction_id = client.get("/transactions").json()[0]["id"]

    response = client.patch(f"/transactions/{transaction_id}", json={"category_id": 999999})

    assert response.status_code == 422


def test_patch_with_unknown_transaction_id_is_404(client: TestClient) -> None:
    category_id = client.get("/categories").json()[0]["id"]

    response = client.patch("/transactions/999999", json={"category_id": category_id})

    assert response.status_code == 404


def test_needs_review_true_for_uncategorized_and_low_confidence_ai(client: TestClient) -> None:
    _upload(client, "a.csv", {})
    transaction_id = client.get("/transactions").json()[0]["id"]
    category_id = client.get("/categories").json()[0]["id"]

    # Uncategorized -> needs_review.
    body = client.get("/transactions").json()[0]
    assert body["needs_review"] is True

    # AI-categorized below the default threshold (0.7) -> needs_review.
    client.app.dependency_overrides[get_categorizer] = lambda: FakeCategorizer(
        confidence=Decimal("0.5")
    )
    categorize_response = client.post("/transactions/categorize")
    assert categorize_response.status_code == 200, categorize_response.text
    body = client.get("/transactions").json()[0]
    assert body["category_source"] == "ai"
    assert body["needs_review"] is True

    # A user override always clears needs_review.
    client.patch(f"/transactions/{transaction_id}", json={"category_id": category_id})
    body = client.get("/transactions").json()[0]
    assert body["needs_review"] is False


def test_needs_review_filter(client: TestClient) -> None:
    _upload(client, "a.csv", {})

    response = client.get("/transactions", params={"needs_review": True})
    assert len(response.json()) == 1

    response = client.get("/transactions", params={"needs_review": False})
    assert len(response.json()) == 0


def test_uncategorized_filter(client: TestClient) -> None:
    _upload(client, "a.csv", {})

    response = client.get("/transactions", params={"uncategorized": True})
    assert len(response.json()) == 1


def test_categorize_endpoint_categorizes_uncategorized_transactions(client: TestClient) -> None:
    _upload(client, "a.csv", {})
    client.app.dependency_overrides[get_categorizer] = lambda: FakeCategorizer()

    response = client.post("/transactions/categorize")

    assert response.status_code == 200, response.text
    assert response.json() == {"categorized": 1}


def test_categorize_endpoint_maps_categorization_error_to_502(client: TestClient) -> None:
    _upload(client, "a.csv", {})

    def _raise() -> FakeCategorizer:
        raise CategorizationError("boom")

    client.app.dependency_overrides[get_categorizer] = _raise

    response = client.post("/transactions/categorize")

    assert response.status_code == 502
