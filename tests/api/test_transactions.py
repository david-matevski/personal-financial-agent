"""DB-backed tests for GET /transactions and GET /accounts (skip if no Postgres)."""

from collections.abc import Sequence
from decimal import Decimal

from fastapi.testclient import TestClient

from finagent.api.deps import get_categorizer, get_extractor
from finagent.categorize.base import (
    CategorizeItem,
    CategoryDecision,
    CategoryExample,
    CategoryOption,
)
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

    # In range for the SMALLINT column but not a real category: repository check.
    response = client.patch(f"/transactions/{transaction_id}", json={"category_id": 32000})

    assert response.status_code == 422


def test_out_of_range_category_ids_are_422_not_a_database_error(client: TestClient) -> None:
    _upload(client, "a.csv", {})
    transaction_id = client.get("/transactions").json()[0]["id"]

    patch = client.patch(f"/transactions/{transaction_id}", json={"category_id": 999999})
    listing = client.get("/transactions", params={"category_id": 999999})

    assert patch.status_code == 422
    assert listing.status_code == 422


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
    transaction_id = client.get("/transactions").json()[0]["id"]
    client.app.dependency_overrides[get_categorizer] = lambda: FakeCategorizer()

    response = client.post("/transactions/categorize")

    assert response.status_code == 200, response.text
    assert response.json() == {"categorized": 1, "remaining": 0, "last_id": transaction_id}


def _multi_upload(client: TestClient) -> dict[str, object]:
    return _upload(
        client,
        "multi.csv",
        {
            "closing_balance": "113.00",
            "transactions": [
                {
                    "posted_date": "2026-01-05",
                    "description": "Row A",
                    "amount": "5.00",
                    "direction": "OUT",
                },
                {
                    "posted_date": "2026-01-06",
                    "description": "Row B",
                    "amount": "8.00",
                    "direction": "OUT",
                },
            ],
        },
    )


def test_categorize_default_mode_is_unchanged(client: TestClient) -> None:
    _multi_upload(client)
    client.app.dependency_overrides[get_categorizer] = lambda: FakeCategorizer()

    response = client.post("/transactions/categorize")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["categorized"] == 2
    assert body["remaining"] == 0


def test_categorize_include_ai_recategorizes_ai_rows_but_not_user_rows(client: TestClient) -> None:
    _multi_upload(client)
    client.app.dependency_overrides[get_categorizer] = lambda: FakeCategorizer()
    assert client.post("/transactions/categorize").status_code == 200

    rows = client.get("/transactions").json()
    row_a = next(r for r in rows if r["description"] == "Row A")
    row_b = next(r for r in rows if r["description"] == "Row B")
    categories = client.get("/categories").json()
    user_category_id = next(c["id"] for c in categories if c["id"] != row_a["category_id"])
    patch_response = client.patch(
        f"/transactions/{row_a['id']}", json={"category_id": user_category_id}
    )
    assert patch_response.status_code == 200, patch_response.text

    new_ai_category_id = next(
        c["id"] for c in categories if c["id"] not in (row_a["category_id"], user_category_id)
    )

    def _decide(
        items: Sequence[CategorizeItem],
        cats: Sequence[CategoryOption],
        examples: Sequence[CategoryExample],
    ) -> list[CategoryDecision]:
        return [
            CategoryDecision(id=item.id, category_id=new_ai_category_id, confidence=Decimal("0.9"))
            for item in items
        ]

    client.app.dependency_overrides[get_categorizer] = lambda: FakeCategorizer(decide=_decide)

    response = client.post("/transactions/categorize", params={"include_ai": "true"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["categorized"] == 1
    assert body["remaining"] == 0

    updated = client.get("/transactions").json()
    updated_a = next(r for r in updated if r["id"] == row_a["id"])
    updated_b = next(r for r in updated if r["id"] == row_b["id"])
    assert updated_a["category_id"] == user_category_id
    assert updated_a["category_source"] == "user"
    assert updated_b["category_id"] == new_ai_category_id
    assert updated_b["category_source"] == "ai"


def test_categorize_after_id_pages_through_the_pool(client: TestClient) -> None:
    _multi_upload(client)
    client.app.dependency_overrides[get_categorizer] = lambda: FakeCategorizer()

    first = client.post("/transactions/categorize", params={"include_ai": "true"})
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["categorized"] == 2
    assert body["remaining"] == 0
    assert body["last_id"] is not None

    second = client.post(
        "/transactions/categorize", params={"include_ai": "true", "after_id": body["last_id"]}
    )

    assert second.status_code == 200, second.text
    assert second.json() == {"categorized": 0, "remaining": 0, "last_id": body["last_id"]}


def test_confirm_flips_source_to_user_and_clears_confidence_and_needs_review(
    client: TestClient,
) -> None:
    _upload(client, "a.csv", {})
    transaction_id = client.get("/transactions").json()[0]["id"]
    client.app.dependency_overrides[get_categorizer] = lambda: FakeCategorizer(
        confidence=Decimal("0.5")
    )
    assert client.post("/transactions/categorize").status_code == 200
    before = client.get("/transactions").json()[0]
    assert before["category_source"] == "ai"
    assert before["needs_review"] is True

    response = client.post("/transactions/confirm", json={"ids": [transaction_id]})

    assert response.status_code == 200, response.text
    assert response.json() == {"confirmed": 1}
    after = client.get("/transactions").json()[0]
    assert after["category_id"] == before["category_id"]
    assert after["category_source"] == "user"
    assert after["category_confidence"] is None
    assert after["needs_review"] is False


def test_confirm_skips_uncategorized_and_unknown_ids(client: TestClient) -> None:
    _upload(client, "a.csv", {})
    transaction_id = client.get("/transactions").json()[0]["id"]

    response = client.post("/transactions/confirm", json={"ids": [transaction_id, 999999]})

    assert response.status_code == 200, response.text
    assert response.json() == {"confirmed": 0}
    row = client.get("/transactions").json()[0]
    assert row["category_id"] is None


def test_confirm_is_idempotent(client: TestClient) -> None:
    _upload(client, "a.csv", {})
    transaction_id = client.get("/transactions").json()[0]["id"]
    client.app.dependency_overrides[get_categorizer] = lambda: FakeCategorizer()
    assert client.post("/transactions/categorize").status_code == 200

    first = client.post("/transactions/confirm", json={"ids": [transaction_id]})
    second = client.post("/transactions/confirm", json={"ids": [transaction_id]})

    assert first.status_code == 200
    assert first.json() == {"confirmed": 1}
    assert second.status_code == 200
    assert second.json() == {"confirmed": 1}


def test_confirm_rejects_empty_list(client: TestClient) -> None:
    response = client.post("/transactions/confirm", json={"ids": []})

    assert response.status_code == 422


def test_confirm_rejects_more_than_500_ids(client: TestClient) -> None:
    response = client.post("/transactions/confirm", json={"ids": list(range(1, 502))})

    assert response.status_code == 422


def test_confirmed_row_is_excluded_from_include_ai_recategorization(
    client: TestClient,
) -> None:
    _upload(client, "a.csv", {})
    transaction_id = client.get("/transactions").json()[0]["id"]
    client.app.dependency_overrides[get_categorizer] = lambda: FakeCategorizer()
    assert client.post("/transactions/categorize").status_code == 200
    assert client.post("/transactions/confirm", json={"ids": [transaction_id]}).status_code == 200

    response = client.post("/transactions/categorize", params={"include_ai": "true"})

    assert response.status_code == 200, response.text
    assert response.json()["categorized"] == 0
    row = client.get("/transactions").json()[0]
    assert row["category_source"] == "user"


def _near_duplicate_setup(client: TestClient) -> tuple[int, int]:
    """Two overlapping statements with the same purchase, reworded/date-shifted.

    Returns (original_id, duplicate_id).
    """
    _upload(client, "jan.csv", {})  # default: 2026-01-05, "Fictional Coffee Co", 5.00
    _upload(
        client,
        "feb.csv",
        {
            "period_start": "2026-01-01",
            "period_end": "2026-02-28",
            "closing_balance": "108.00",
            "transactions": [
                {
                    "posted_date": "2026-01-07",
                    "description": "COFFEE CO TORONTO",
                    "amount": "5.00",
                    "direction": "OUT",
                },
                {
                    "posted_date": "2026-02-01",
                    "description": "Fictional Streaming Co",
                    "amount": "3.00",
                    "direction": "OUT",
                },
            ],
        },
    )
    rows = client.get("/transactions", params={"limit": 100}).json()
    original = next(r for r in rows if r["description"] == "Fictional Coffee Co")
    duplicate = next(r for r in rows if r["description"] == "COFFEE CO TORONTO")
    return original["id"], duplicate["id"]


def test_transaction_out_exposes_duplicate_fields_when_flagged(client: TestClient) -> None:
    original_id, duplicate_id = _near_duplicate_setup(client)

    rows = client.get("/transactions", params={"limit": 100}).json()
    duplicate_row = next(r for r in rows if r["id"] == duplicate_id)
    original_row = next(r for r in rows if r["id"] == original_id)

    assert duplicate_row["possible_duplicate_of"] == original_id
    assert duplicate_row["duplicate_candidate"]["id"] == original_id
    assert duplicate_row["duplicate_candidate"]["description"] == "Fictional Coffee Co"
    assert duplicate_row["removed"] is False
    assert original_row["possible_duplicate_of"] is None
    assert original_row["duplicate_candidate"] is None


def test_possible_duplicates_filter(client: TestClient) -> None:
    _, duplicate_id = _near_duplicate_setup(client)

    response = client.get("/transactions", params={"possible_duplicates": "true"})

    assert response.status_code == 200
    body = response.json()
    assert [r["id"] for r in body] == [duplicate_id]


def test_duplicate_action_keep_both(client: TestClient) -> None:
    _, duplicate_id = _near_duplicate_setup(client)

    response = client.post(f"/transactions/{duplicate_id}/duplicate", json={"action": "keep_both"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["possible_duplicate_of"] is None
    assert client.get("/transactions", params={"possible_duplicates": "true"}).json() == []


def test_duplicate_action_remove_hides_from_list_and_summary(client: TestClient) -> None:
    original_id, duplicate_id = _near_duplicate_setup(client)
    before_summary = client.get("/categories/summary").json()
    before_count = sum(row["count"] for row in before_summary)

    response = client.post(f"/transactions/{duplicate_id}/duplicate", json={"action": "remove"})

    assert response.status_code == 200, response.text
    assert response.json()["removed"] is True

    visible_ids = [r["id"] for r in client.get("/transactions", params={"limit": 100}).json()]
    assert duplicate_id not in visible_ids
    assert original_id in visible_ids

    after_summary = client.get("/categories/summary").json()
    after_count = sum(row["count"] for row in after_summary)
    assert after_count == before_count - 1

    with_removed_ids = [
        r["id"]
        for r in client.get(
            "/transactions", params={"limit": 100, "include_removed": "true"}
        ).json()
    ]
    assert duplicate_id in with_removed_ids


def test_duplicate_action_restore(client: TestClient) -> None:
    _, duplicate_id = _near_duplicate_setup(client)
    client.post(f"/transactions/{duplicate_id}/duplicate", json={"action": "remove"})

    response = client.post(f"/transactions/{duplicate_id}/duplicate", json={"action": "restore"})

    assert response.status_code == 200, response.text
    assert response.json()["removed"] is False
    visible_ids = [r["id"] for r in client.get("/transactions", params={"limit": 100}).json()]
    assert duplicate_id in visible_ids


def test_duplicate_action_unknown_transaction_is_404(client: TestClient) -> None:
    response = client.post("/transactions/999999/duplicate", json={"action": "keep_both"})

    assert response.status_code == 404


def test_duplicate_action_unknown_action_is_422(client: TestClient) -> None:
    _, duplicate_id = _near_duplicate_setup(client)

    response = client.post(f"/transactions/{duplicate_id}/duplicate", json={"action": "bogus"})

    assert response.status_code == 422


def test_categorize_endpoint_maps_categorization_error_to_502(client: TestClient) -> None:
    _upload(client, "a.csv", {})

    def _raise() -> FakeCategorizer:
        raise CategorizationError("boom")

    client.app.dependency_overrides[get_categorizer] = _raise

    response = client.post("/transactions/categorize")

    assert response.status_code == 502
