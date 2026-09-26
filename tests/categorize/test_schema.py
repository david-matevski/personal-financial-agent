"""Tests for finagent.categorize.schema.decode_decisions (pure, no I/O)."""

from decimal import Decimal

from finagent.categorize.base import CategoryOption
from finagent.categorize.schema import CategorizationOutput, CategorizedItem, decode_decisions

_CATEGORIES = [
    CategoryOption(id=1, name="Grocery", description="supermarkets"),
    CategoryOption(id=2, name="Dining", description="restaurants"),
]


def test_known_category_name_maps_to_its_id() -> None:
    output = CategorizationOutput(
        items=[CategorizedItem(id=10, category_name="Grocery", confidence=0.9)]
    )

    decisions = decode_decisions(output, valid_ids={10}, categories=_CATEGORIES)

    assert len(decisions) == 1
    assert decisions[0].id == 10
    assert decisions[0].category_id == 1
    assert decisions[0].confidence == Decimal("0.900")


def test_confidence_is_quantized_to_three_decimal_places() -> None:
    output = CategorizationOutput(
        items=[CategorizedItem(id=10, category_name="Grocery", confidence=0.123456)]
    )

    decisions = decode_decisions(output, valid_ids={10}, categories=_CATEGORIES)

    assert decisions[0].confidence == Decimal("0.123")


def test_unknown_category_name_is_dropped() -> None:
    output = CategorizationOutput(
        items=[CategorizedItem(id=10, category_name="Not A Real Category", confidence=0.9)]
    )

    decisions = decode_decisions(output, valid_ids={10}, categories=_CATEGORIES)

    assert decisions == []


def test_missing_id_is_dropped() -> None:
    output = CategorizationOutput(
        items=[CategorizedItem(id=None, category_name="Grocery", confidence=0.9)]
    )

    decisions = decode_decisions(output, valid_ids={10}, categories=_CATEGORIES)

    assert decisions == []


def test_id_not_in_the_original_batch_is_dropped() -> None:
    output = CategorizationOutput(
        items=[CategorizedItem(id=999, category_name="Grocery", confidence=0.9)]
    )

    decisions = decode_decisions(output, valid_ids={10}, categories=_CATEGORIES)

    assert decisions == []


def test_mixed_batch_keeps_only_the_valid_items() -> None:
    output = CategorizationOutput(
        items=[
            CategorizedItem(id=10, category_name="Grocery", confidence=0.9),
            CategorizedItem(id=11, category_name="Nonexistent", confidence=0.5),
            CategorizedItem(id=None, category_name="Dining", confidence=0.5),
        ]
    )

    decisions = decode_decisions(output, valid_ids={10, 11}, categories=_CATEGORIES)

    assert len(decisions) == 1
    assert decisions[0].id == 10
