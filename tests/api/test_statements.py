"""DB-backed tests for POST/GET /statements (skip if Postgres is unreachable)."""

from fastapi.testclient import TestClient

from finagent.api.deps import get_extractor
from finagent.core.errors import ExtractionError
from tests.api.helpers import FakeExtractor, make_extraction

_CSV_BYTES = b"whatever, the fake extractor ignores this"
_JUNK_BYTES = b"\x00\x01\x02\xff\xfe\xfd not a real statement format"


def test_upload_new_statement_is_verified_and_persists_rows(client: TestClient) -> None:
    extractor = FakeExtractor([make_extraction()])
    client.app.dependency_overrides[get_extractor] = lambda: extractor

    response = client.post("/statements", files={"file": ("statement.csv", _CSV_BYTES, "text/csv")})

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "VERIFIED"
    assert body["already_imported"] is False
    assert body["transactions_inserted"] == 1
    assert body["transactions_skipped_duplicate"] == 0
    assert len(extractor.calls) == 1


def test_reupload_same_bytes_is_a_noop_and_skips_extraction(client: TestClient) -> None:
    extractor = FakeExtractor([make_extraction()])
    client.app.dependency_overrides[get_extractor] = lambda: extractor

    first = client.post("/statements", files={"file": ("statement.csv", _CSV_BYTES, "text/csv")})
    assert first.status_code == 201
    assert len(extractor.calls) == 1

    second = client.post("/statements", files={"file": ("statement.csv", _CSV_BYTES, "text/csv")})

    assert second.status_code in (200, 201)
    body = second.json()
    assert body["already_imported"] is True
    assert body["statement_id"] == first.json()["statement_id"]
    # The whole point of the sha256 short-circuit: no extra API spend.
    assert len(extractor.calls) == 1


def test_failed_extraction_result_persists_with_zero_transactions(client: TestClient) -> None:
    failed = make_extraction(
        opening_balance=None,
        closing_balance=None,
        total_money_out=None,
        total_money_in=None,
        transactions=[],
    )
    extractor = FakeExtractor([failed])
    client.app.dependency_overrides[get_extractor] = lambda: extractor

    response = client.post("/statements", files={"file": ("failed.csv", _CSV_BYTES, "text/csv")})

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "FAILED"
    assert body["transactions_inserted"] == 0
    assert body["problems"]


def test_get_statement_detail_excludes_extraction_by_default(client: TestClient) -> None:
    extractor = FakeExtractor([make_extraction()])
    client.app.dependency_overrides[get_extractor] = lambda: extractor
    upload = client.post("/statements", files={"file": ("statement.csv", _CSV_BYTES, "text/csv")})
    statement_id = upload.json()["statement_id"]

    default_response = client.get(f"/statements/{statement_id}")
    with_extraction_response = client.get(
        f"/statements/{statement_id}", params={"include_extraction": "true"}
    )

    assert default_response.json()["extraction"] is None
    assert with_extraction_response.json()["extraction"]["issuer"] == "TD"


def test_list_statements_omits_extraction_and_is_newest_first(client: TestClient) -> None:
    extractor = FakeExtractor([make_extraction(), make_extraction()])
    client.app.dependency_overrides[get_extractor] = lambda: extractor
    client.post("/statements", files={"file": ("one.csv", _CSV_BYTES, "text/csv")})
    second = client.post("/statements", files={"file": ("two.csv", _CSV_BYTES + b"x", "text/csv")})

    response = client.get("/statements")

    assert response.status_code == 200
    body = response.json()
    assert "extraction" not in body[0]
    assert body[0]["id"] == second.json()["statement_id"]


def test_get_statement_not_found_returns_404(client: TestClient) -> None:
    response = client.get("/statements/999999")

    assert response.status_code == 404


def test_extraction_error_from_extractor_returns_502(client: TestClient) -> None:
    extractor = FakeExtractor(error=ExtractionError("boom"))
    client.app.dependency_overrides[get_extractor] = lambda: extractor

    response = client.post("/statements", files={"file": ("statement.csv", _CSV_BYTES, "text/csv")})

    assert response.status_code == 502
    assert "boom" not in response.text


def test_statement_summary_includes_period_derived_and_skipped_fields(
    client: TestClient,
) -> None:
    extractor = FakeExtractor([make_extraction()])
    client.app.dependency_overrides[get_extractor] = lambda: extractor

    response = client.post("/statements", files={"file": ("statement.csv", _CSV_BYTES, "text/csv")})
    statement_id = response.json()["statement_id"]

    detail = client.get(f"/statements/{statement_id}").json()
    assert detail["period_derived"] is False  # make_extraction prints a period
    assert detail["transactions_skipped"] == 0
    assert detail["overlaps"] == []


def test_overlapping_statements_are_listed_on_both(client: TestClient) -> None:
    first_extractor = FakeExtractor([make_extraction()])
    client.app.dependency_overrides[get_extractor] = lambda: first_extractor
    first = client.post("/statements", files={"file": ("jan.csv", _CSV_BYTES, "text/csv")})
    first_id = first.json()["statement_id"]

    second_extraction = make_extraction(
        period_start="2026-01-20",
        period_end="2026-02-20",
        closing_balance="102.00",
        transactions=[
            {
                "posted_date": "2026-02-01",
                "description": "Fictional Streaming Co",
                "amount": "2.00",
                "direction": "OUT",
            }
        ],
    )
    second_extractor = FakeExtractor([second_extraction])
    client.app.dependency_overrides[get_extractor] = lambda: second_extractor
    second = client.post("/statements", files={"file": ("feb.csv", _CSV_BYTES + b"x", "text/csv")})
    second_id = second.json()["statement_id"]

    first_detail = client.get(f"/statements/{first_id}").json()
    second_detail = client.get(f"/statements/{second_id}").json()

    assert [o["statement_id"] for o in first_detail["overlaps"]] == [second_id]
    assert [o["statement_id"] for o in second_detail["overlaps"]] == [first_id]


def test_unsupported_statement_format_returns_415(client: TestClient) -> None:
    extractor = FakeExtractor([make_extraction()])
    client.app.dependency_overrides[get_extractor] = lambda: extractor

    response = client.post(
        "/statements", files={"file": ("junk.bin", _JUNK_BYTES, "application/octet-stream")}
    )

    assert response.status_code == 415
    assert len(extractor.calls) == 0
