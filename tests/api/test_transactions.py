"""DB-backed tests for GET /transactions and GET /accounts (skip if no Postgres)."""

from fastapi.testclient import TestClient

from finagent.api.deps import get_extractor
from tests.api.helpers import FakeExtractor, make_extraction


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
