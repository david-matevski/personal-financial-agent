"""Shared test doubles for tests/api.

Kept separate from conftest.py so plain modules (not just fixtures) can
import them without pulling in pytest fixture machinery.
"""

from finagent.ingest.document import SourceDocument
from finagent.ingest.extract.schema import StatementExtraction


class FakeExtractor:
    """A ``StatementExtractor`` stub returning canned results in order.

    Records every call (filename, feedback) so tests can assert the
    extractor was -- or crucially, was *not* -- invoked (e.g. re-uploading
    an already-imported file must not call it again).
    """

    def __init__(
        self,
        results: list[StatementExtraction] | None = None,
        error: Exception | None = None,
    ) -> None:
        self._results = results or []
        self._error = error
        self.calls: list[tuple[str, str | None]] = []

    def extract(self, doc: SourceDocument, feedback: str | None = None) -> StatementExtraction:
        self.calls.append((doc.filename, feedback))
        if self._error is not None:
            raise self._error
        return self._results[min(len(self.calls) - 1, len(self._results) - 1)]


def make_extraction(**overrides: object) -> StatementExtraction:
    """A verified-by-default statement extraction, synthetic values only."""
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
