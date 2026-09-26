"""Categorization backend contract.

LLM access goes only through this Protocol (AGENTS.md §3): tests use fakes,
and no test ever calls the real API. The Anthropic implementation lives in
``finagent.categorize.anthropic``.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal, Protocol


@dataclass(frozen=True)
class CategorizeItem:
    """One transaction to categorize, as presented to the categorizer."""

    id: int
    description: str
    amount: Decimal
    direction: Literal["OUT", "IN"]
    posted_date: date


@dataclass(frozen=True)
class CategoryOption:
    """One category the model may choose, with its owner-written hint."""

    id: int
    name: str
    description: str | None


@dataclass(frozen=True)
class CategoryExample:
    """One past categorization decision, offered as a preference example."""

    description: str
    category_name: str


@dataclass(frozen=True)
class CategoryDecision:
    """The categorizer's decision for one item, already mapped to a category id."""

    id: int
    category_id: int
    confidence: Decimal


class TransactionCategorizer(Protocol):
    """Assigns each item a category from ``categories``, informed by ``examples``."""

    def categorize(
        self,
        items: Sequence[CategorizeItem],
        categories: Sequence[CategoryOption],
        examples: Sequence[CategoryExample],
    ) -> list[CategoryDecision]:
        """Return one decision per item that could be confidently categorized.

        An item may be dropped (no decision returned for its id) if the
        model's answer for it was unusable -- see
        ``finagent.categorize.schema.decode_decisions``. It stays
        uncategorized and is retried on a later pass.
        """
        ...
