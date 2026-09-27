"""Tests for finagent.domain.account_matching."""

from finagent.domain.account_matching import (
    ExistingAccountRef,
    names_compatible,
    resolve_account_match,
)


def test_identical_names_are_compatible() -> None:
    assert names_compatible("TD", "TD") is True


def test_prefix_names_are_compatible() -> None:
    assert names_compatible("TD", "TD BANK") is True
    assert names_compatible("TD BANK", "TD") is True


def test_subset_tokens_are_compatible() -> None:
    assert names_compatible("CIBC", "CIBC BANK") is True


def test_unrelated_names_are_not_compatible() -> None:
    assert names_compatible("TD", "RBC") is False


def test_names_equal_ignoring_spaces_are_compatible() -> None:
    assert names_compatible("TD BANK", "TDBANK") is True


def test_punctuation_is_stripped_before_comparing() -> None:
    assert names_compatible("TD.", "TD") is True


def test_disjoint_multiword_names_are_not_compatible() -> None:
    assert names_compatible("TD BANK", "ROYAL BANK") is False


def test_resolve_exact_match_wins() -> None:
    existing = [ExistingAccountRef(id=1, issuer="TD"), ExistingAccountRef(id=2, issuer="TD BANK")]
    match = resolve_account_match(existing, issuer="TD BANK")
    assert match is not None
    assert match.id == 2


def test_resolve_single_compatible_candidate() -> None:
    existing = [ExistingAccountRef(id=1, issuer="TD")]
    match = resolve_account_match(existing, issuer="TD BANK")
    assert match is not None
    assert match.id == 1


def test_resolve_no_compatible_candidate_returns_none() -> None:
    existing = [ExistingAccountRef(id=1, issuer="RBC")]
    assert resolve_account_match(existing, issuer="TD") is None


def test_resolve_ambiguous_candidates_returns_none() -> None:
    existing = [
        ExistingAccountRef(id=1, issuer="TD BANK"),
        ExistingAccountRef(id=2, issuer="TD FINANCIAL"),
    ]
    # Both existing issuers are compatible with "TD" (prefix rule) but not
    # with each other -- genuine ambiguity must not silently pick one.
    match = resolve_account_match(existing, issuer="TD")
    assert match is None


def test_resolve_empty_existing_returns_none() -> None:
    assert resolve_account_match([], issuer="TD") is None
