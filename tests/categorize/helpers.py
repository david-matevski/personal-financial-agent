"""Shared test doubles for categorization tests.

Kept separate from conftest.py so plain modules (not just fixtures) can
import them, mirroring tests/api/helpers.py's FakeExtractor.
"""

from collections.abc import Callable, Sequence
from decimal import Decimal

from finagent.categorize.base import (
    CategorizeItem,
    CategoryDecision,
    CategoryExample,
    CategoryOption,
)

_Decide = Callable[
    [Sequence[CategorizeItem], Sequence[CategoryOption], Sequence[CategoryExample]],
    list[CategoryDecision],
]


class FakeCategorizer:
    """A ``TransactionCategorizer`` stub.

    By default assigns every item to the first given category at a fixed
    confidence; pass ``decide`` for custom per-item behaviour, or ``error``
    to simulate a categorizer failure. Records every call's items so tests
    can assert on batching.
    """

    def __init__(
        self,
        *,
        decide: _Decide | None = None,
        error: Exception | None = None,
        confidence: Decimal = Decimal("0.900"),
    ) -> None:
        self._decide = decide
        self._error = error
        self._confidence = confidence
        self.calls: list[list[CategorizeItem]] = []

    def categorize(
        self,
        items: Sequence[CategorizeItem],
        categories: Sequence[CategoryOption],
        examples: Sequence[CategoryExample],
    ) -> list[CategoryDecision]:
        self.calls.append(list(items))
        if self._error is not None:
            raise self._error
        if self._decide is not None:
            return self._decide(items, categories, examples)
        if not categories:
            return []
        default_category_id = categories[0].id
        return [
            CategoryDecision(
                id=item.id, category_id=default_category_id, confidence=self._confidence
            )
            for item in items
        ]
