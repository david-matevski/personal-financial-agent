"""Tests for finagent.ingest.pipeline: load -> extract -> normalize -> validate, with retry."""

from finagent.ingest.document import SourceDocument
from finagent.ingest.extract.schema import StatementExtraction
from finagent.ingest.pipeline import extract_statement
from finagent.ingest.validate import ValidationStatus

_CSV_BYTES = "Date,Amount\n2026-01-05,5.00\n".encode("utf-8-sig")


class FakeExtractor:
    """Returns canned extractions in order, one per call; records feedback seen."""

    def __init__(self, results: list[StatementExtraction]) -> None:
        self._results = results
        self.feedbacks: list[str | None] = []

    def extract(self, doc: SourceDocument, feedback: str | None = None) -> StatementExtraction:
        self.feedbacks.append(feedback)
        return self._results[len(self.feedbacks) - 1]


def _extraction(**overrides: object) -> StatementExtraction:
    defaults: dict[str, object] = {
        "issuer": "TD",
        "account_name": "TD Rewards Visa",
        "account_last4": "1234",
        "account_type": "CREDIT",
        "currency": "CAD",
        "period_start": "2026-01-01",
        "period_end": "2026-01-31",
        "opening_balance": "100.00",
        "closing_balance": "105.00",
        "total_money_out": None,
        "total_money_in": None,
        "transactions": [
            {
                "posted_date": "2026-01-05",
                "description": "Fictional Coffee Co",
                "amount": "5.00",
                "direction": "OUT",
            }
        ],
    }
    defaults.update(overrides)
    return StatementExtraction.model_validate(defaults)


def test_first_attempt_verified_needs_no_retry() -> None:
    extractor = FakeExtractor([_extraction()])

    result = extract_statement("statement.csv", _CSV_BYTES, extractor)

    assert result.status is ValidationStatus.VERIFIED
    assert result.attempts == 1
    assert len(extractor.feedbacks) == 1


def test_retry_triggered_with_feedback_and_succeeds_on_second_attempt() -> None:
    wrong = _extraction(
        transactions=[
            {
                "posted_date": "2026-01-05",
                "description": "Fictional Coffee Co",
                "amount": "3.00",  # doesn't reconcile: opening 100 -> closing 105 needs 5.00
                "direction": "OUT",
            }
        ]
    )
    corrected = _extraction()  # sums to 5.00, reconciles
    extractor = FakeExtractor([wrong, corrected])

    result = extract_statement("statement.csv", _CSV_BYTES, extractor)

    assert result.status is ValidationStatus.VERIFIED
    assert result.attempts == 2
    assert len(extractor.feedbacks) == 2
    assert extractor.feedbacks[0] is None
    assert extractor.feedbacks[1] is not None
    assert "difference" in extractor.feedbacks[1]


def test_retry_still_wrong_stays_failed() -> None:
    wrong = _extraction(
        transactions=[
            {
                "posted_date": "2026-01-05",
                "description": "Fictional Coffee Co",
                "amount": "3.00",
                "direction": "OUT",
            }
        ]
    )
    still_wrong = _extraction(
        transactions=[
            {
                "posted_date": "2026-01-05",
                "description": "Fictional Coffee Co",
                "amount": "2.00",
                "direction": "OUT",
            }
        ]
    )
    extractor = FakeExtractor([wrong, still_wrong])

    result = extract_statement("statement.csv", _CSV_BYTES, extractor)

    assert result.status is ValidationStatus.FAILED
    assert result.attempts == 2


def test_no_retry_when_failure_has_no_numeric_discrepancy() -> None:
    # No opening/closing or totals printed, and zero transactions: FAILED
    # with no discrepancy to feed back, so no retry is attempted.
    empty = _extraction(
        opening_balance=None, closing_balance=None, total_money_out=None, transactions=[]
    )
    extractor = FakeExtractor([empty])

    result = extract_statement("statement.csv", _CSV_BYTES, extractor)

    assert result.status is ValidationStatus.FAILED
    assert result.attempts == 1
    assert len(extractor.feedbacks) == 1
