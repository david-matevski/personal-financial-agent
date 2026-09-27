"""Tests for finagent.domain.similarity."""

from finagent.domain.similarity import descriptions_are_similar


def test_identical_descriptions_are_similar() -> None:
    assert descriptions_are_similar("STARBUCKS #1234", "STARBUCKS #1234") is True


def test_reformatted_same_purchase_is_similar() -> None:
    # Same merchant, digits/punctuation differ -- token Jaccard >= 0.5.
    assert descriptions_are_similar("STARBUCKS #1234 TORONTO", "STARBUCKS TORONTO ON") is True


def test_containment_counts_as_similar() -> None:
    assert descriptions_are_similar("NETFLIX.COM", "NETFLIX.COM MONTHLY SUB") is True


def test_unrelated_merchants_are_not_similar() -> None:
    assert descriptions_are_similar("STARBUCKS COFFEE", "SHELL GAS STATION") is False


def test_low_overlap_is_not_similar() -> None:
    # Only one token in common out of four total -- Jaccard well below 0.5.
    assert descriptions_are_similar("AMAZON MARKETPLACE PAYMENTS", "AMAZON PRIME VIDEO") is False


def test_digits_and_punctuation_are_ignored() -> None:
    assert descriptions_are_similar("COFFEE SHOP #42", "COFFEE-SHOP 42!!") is True


def test_empty_descriptions_are_not_similar() -> None:
    assert descriptions_are_similar("", "") is False
    assert descriptions_are_similar("123", "456") is False  # digits only -> no tokens
