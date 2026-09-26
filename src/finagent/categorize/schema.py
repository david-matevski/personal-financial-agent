"""Structured-output schema for transaction categorization.

The model returns a category *name* (validated against the given list) and
a confidence score, never a category id directly -- mapping name -> id
happens here in code so an invented or misspelled category name is caught
deterministically rather than trusted (AGENTS.md §3: "The LLM transcribes,
code interprets").
"""

from collections.abc import Sequence
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from finagent.categorize.base import CategoryDecision, CategoryOption


class CategorizedItem(BaseModel):
    """One item's categorization decision, as returned by the model."""

    model_config = ConfigDict(extra="forbid")

    id: int | None = None
    category_name: str
    # A model confidence score, not a monetary amount -- a plain float is
    # fine here (it's converted to a quantized Decimal in decode_decisions
    # below). AGENTS.md's "Decimal, never float" rule is about money.
    confidence: float


class CategorizationOutput(BaseModel):
    """The full structured response for one categorization batch."""

    model_config = ConfigDict(extra="forbid")

    items: list[CategorizedItem] = Field(default_factory=list)


def decode_decisions(
    output: CategorizationOutput,
    *,
    valid_ids: set[int],
    categories: Sequence[CategoryOption],
) -> list[CategoryDecision]:
    """Map the model's per-item output to ``CategoryDecision``s.

    An item is dropped -- not raised as an error -- when its id is missing
    or doesn't match one of the items sent to the model, or when
    ``category_name`` isn't one of ``categories``. A dropped item stays
    uncategorized and is retried on a later categorization pass.
    """
    name_to_id = {category.name: category.id for category in categories}
    decisions: list[CategoryDecision] = []
    for item in output.items:
        if item.id is None or item.id not in valid_ids:
            continue
        category_id = name_to_id.get(item.category_name)
        if category_id is None:
            continue
        confidence = Decimal(str(item.confidence)).quantize(Decimal("0.001"))
        decisions.append(
            CategoryDecision(id=item.id, category_id=category_id, confidence=confidence)
        )
    return decisions
