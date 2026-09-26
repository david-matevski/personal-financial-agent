"""Pure description similarity, for near-duplicate transaction detection.

Two transaction lines with the same amount and nearby dates are flagged as
possible duplicates only if their descriptions also look alike -- e.g. the
same purchase transcribed slightly differently across two overlapping
statement imports (AGENTS.md: no per-issuer parsers, so this stays generic).
"""

import re

_LETTERS_RE = re.compile(r"[^A-Z\s]")
_WHITESPACE_RE = re.compile(r"\s+")
_MIN_TOKEN_LENGTH = 2
_JACCARD_THRESHOLD = 0.5


def _normalize(description: str) -> str:
    """Uppercase, digits/punctuation stripped, whitespace collapsed."""
    letters_only = _LETTERS_RE.sub(" ", description.upper())
    return _WHITESPACE_RE.sub(" ", letters_only).strip()


def _tokens(description: str) -> set[str]:
    return {tok for tok in _normalize(description).split(" ") if len(tok) >= _MIN_TOKEN_LENGTH}


def descriptions_are_similar(a: str, b: str) -> bool:
    """True if two transaction descriptions plausibly describe the same purchase.

    True when, after normalizing (uppercase, digits and punctuation
    stripped, short tokens dropped): one normalized description contains the
    other, or their token sets have a Jaccard similarity of at least 0.5.
    """
    norm_a, norm_b = _normalize(a), _normalize(b)
    if norm_a and norm_b and (norm_a in norm_b or norm_b in norm_a):
        return True

    tokens_a, tokens_b = _tokens(a), _tokens(b)
    if not tokens_a or not tokens_b:
        return False

    intersection = len(tokens_a & tokens_b)
    union = len(tokens_a | tokens_b)
    return (intersection / union) >= _JACCARD_THRESHOLD
