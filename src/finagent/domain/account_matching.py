"""Pure account-identity matching (AGENTS.md §3: no per-issuer parsers).

Backstops the extraction model's own "known accounts" hint (see
``StatementExtractor.extract``): even if the model doesn't pick the exact
issuer name already on record, minor drift like "TD" vs "TD BANK" must still
resolve to the same account rather than spawning a duplicate one with
duplicated transactions.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TypeVar

_PUNCTUATION_RE = re.compile(r"[^\w\s]")


def _normalize(name: str) -> str:
    """Uppercase, punctuation-stripped form of a name, for comparison."""
    return _PUNCTUATION_RE.sub("", name).upper().strip()


def _tokens(name: str) -> list[str]:
    return _normalize(name).split()


def names_compatible(a: str, b: str) -> bool:
    """True if two issuer names plausibly refer to the same institution.

    After normalization (uppercase, punctuation stripped): equal ignoring
    spaces, or one name's tokens are a prefix or subset of the other's (e.g.
    "TD" vs "TD BANK", "CIBC" vs "CIBC BANK"). Deliberately conservative:
    "TD" and "RBC" share no tokens and are never compatible.
    """
    norm_a, norm_b = _normalize(a), _normalize(b)
    if norm_a.replace(" ", "") == norm_b.replace(" ", ""):
        return True

    tokens_a, tokens_b = _tokens(a), _tokens(b)
    if not tokens_a or not tokens_b:
        return False

    shorter, longer = (
        (tokens_a, tokens_b) if len(tokens_a) <= len(tokens_b) else (tokens_b, tokens_a)
    )
    if longer[: len(shorter)] == shorter:
        return True
    return set(shorter) <= set(longer)


@dataclass(frozen=True)
class ExistingAccountRef:
    """The minimal identity of one existing account, for match resolution."""

    id: int
    issuer: str


_T = TypeVar("_T", bound=ExistingAccountRef)


def resolve_account_match(existing: Sequence[_T], *, issuer: str) -> _T | None:
    """Pick which (if any) of ``existing`` accounts an extracted issuer belongs to.

    ``existing`` must already be filtered to accounts sharing the extracted
    statement's (last4, account_type) -- this function only disambiguates
    issuer-name drift among those. An exact issuer match always wins;
    otherwise, if exactly one candidate has a compatible name, it's reused;
    a genuine ambiguity (more than one compatible candidate) or no
    compatible candidate returns ``None``, signalling "create a new
    account" to the caller.
    """
    for ref in existing:
        if ref.issuer == issuer:
            return ref

    compatible = [ref for ref in existing if names_compatible(ref.issuer, issuer)]
    if len(compatible) == 1:
        return compatible[0]
    return None
