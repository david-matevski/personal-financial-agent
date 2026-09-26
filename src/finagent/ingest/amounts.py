"""Generic, issuer-agnostic parsing of a printed amount string (AGENTS.md §3).

``interpret_amount`` reads an amount exactly as a statement printed it --
currency symbol/code, grouping, decimal separator, any ``CR``/``DR`` text
marker, and any sign (minus/parentheses) -- and returns the magnitude plus
what the *document* printed, split into two independent signals:

- ``marker``: a **textual** credit/debit marker (``CR``, ``DR``, ``DB``).
- ``negative``: a **sign** marker (a leading/trailing minus variant, or
  wrapping parentheses).

These are kept apart deliberately: what they *mean* is context-dependent.
A DEBIT (bank) account routinely prints a healthy balance as "1,234.56 CR"
-- text CR there means "in credit" (positive), not "negative" -- whereas a
minus sign on the same statement means overdrawn (negative). Collapsing
both into one "credit" concept (an earlier version of this module did)
made a normal CR-suffixed bank balance indistinguishable from an actual
overdraft. See ``finagent.ingest.normalize`` for how each context (a
transaction amount vs. a CREDIT-account balance vs. a DEBIT-account
balance) combines ``marker`` and ``negative`` into a sign (AGENTS.md task
spec §2) -- this module intentionally knows nothing about that.

It never guesses based on which issuer printed the statement: every rule
here is about the characters themselves, never about issuer identity
(AGENTS.md §3: "No per-issuer parsers").
"""

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from finagent.core.errors import ParseError

Marker = Literal["credit", "debit"]
_FoundKind = Literal["credit_text", "debit_text", "negative", "ignore"]

# Thousands separators that can *never* be a decimal separator.
_THOUSANDS_ONLY_CHARS = frozenset("    '")
# The two characters that can be either a decimal separator or a thousands
# separator, depending on context (AGENTS.md task spec §1).
_DOT_COMMA = frozenset(".,")
_ALLOWED_NUMERAL_CHARS = frozenset("0123456789") | _THOUSANDS_ONLY_CHARS | _DOT_COMMA

# Longest-prefix-first so "CA$"/"US$" are matched before the bare "$" inside
# them would otherwise steal a partial match.
_CURRENCY_SYMBOLS = ("CA$", "US$", "C$", "$", "€", "£")

# Leading sign-marker dash variants (AGENTS.md task spec §1): a trailing
# dash is intentionally narrower (plain hyphen-minus only).
_LEADING_NEGATIVE_DASHES = ("-", "−", "–", "‑")  # noqa: RUF001


@dataclass(frozen=True)
class PrintedAmount:
    """One amount, exactly as interpreted from its printed representation."""

    magnitude: Decimal
    marker: Marker | None
    """A textual ``CR``/``DR``/``DB`` marker, if the document printed one."""
    negative: bool = False
    """A sign marker: a leading/trailing minus variant, or parentheses."""


def _strip_currency_symbol(s: str, *, leading: bool) -> str | None:
    for token in _CURRENCY_SYMBOLS:
        if leading and s.startswith(token):
            return s[len(token) :].lstrip()
        if not leading and s.endswith(token):
            return s[: -len(token)].rstrip()
    return None


def _strip_leading_currency_code(s: str) -> str | None:
    if len(s) < 3 or not s[:3].isalpha():
        return None
    rest = s[3:].lstrip()
    if rest and (rest[0].isdigit() or rest[0] in "(+-−–‑"):  # noqa: RUF001
        return rest
    return None


def _strip_trailing_currency_code(s: str) -> str | None:
    if len(s) < 3 or not s[-3:].isalpha():
        return None
    rest = s[:-3].rstrip()
    if rest and (rest[-1].isdigit() or rest[-1] == ")"):
        return rest
    return None


def _strip_leading_marker(s: str) -> tuple[str, _FoundKind] | None:
    for dash in _LEADING_NEGATIVE_DASHES:
        if s.startswith(dash):
            return s[len(dash) :].lstrip(), "negative"
    lowered = s.lower()
    if lowered.startswith("cr."):
        return s[3:].lstrip(), "credit_text"
    if lowered.startswith("cr"):
        return s[2:].lstrip(), "credit_text"
    if lowered.startswith("dr"):
        return s[2:].lstrip(), "debit_text"
    if lowered.startswith("db"):
        return s[2:].lstrip(), "debit_text"
    if s.startswith("+"):
        return s[1:].lstrip(), "ignore"
    return None


def _strip_trailing_marker(s: str) -> tuple[str, _FoundKind] | None:
    lowered = s.lower()
    if lowered.endswith("cr."):
        return s[:-3].rstrip(), "credit_text"
    if lowered.endswith("cr"):
        return s[:-2].rstrip(), "credit_text"
    if lowered.endswith("dr"):
        return s[:-2].rstrip(), "debit_text"
    if lowered.endswith("db"):
        return s[:-2].rstrip(), "debit_text"
    if s.endswith("-"):
        return s[:-1].rstrip(), "negative"
    return None


def _strip_wrapping_parens(s: str) -> str | None:
    """Strip a pair of parentheses wrapping the whole remaining string.

    Checked on every pass (not just once up front) so a marker printed
    outside the parentheses, e.g. "(270.46) CR", is stripped first and the
    parentheses are recognized once they end up wrapping the whole string.
    """
    if len(s) >= 2 and s[0] == "(" and s[-1] == ")":
        return s[1:-1].strip()
    return None


@dataclass
class _MarkerState:
    marker: Marker | None = None
    negative: bool = False


def _apply_found(state: _MarkerState, found: _FoundKind) -> None:
    if found == "ignore":
        return
    if found == "negative":
        state.negative = True
        return
    new_marker: Marker = "credit" if found == "credit_text" else "debit"
    if state.marker is not None and state.marker != new_marker:
        raise ParseError("conflicting credit and debit markers in amount")
    state.marker = new_marker


def _strip_tokens(s: str, state: _MarkerState) -> str:
    """Strip at most one recognized currency/marker/sign token from either edge."""
    new_s = _strip_wrapping_parens(s)
    if new_s is not None:
        state.negative = True
        return new_s
    new_s = _strip_currency_symbol(s, leading=True)
    if new_s is not None:
        return new_s
    new_s = _strip_currency_symbol(s, leading=False)
    if new_s is not None:
        return new_s
    new_s = _strip_leading_currency_code(s)
    if new_s is not None:
        return new_s
    new_s = _strip_trailing_currency_code(s)
    if new_s is not None:
        return new_s
    leading_marker = _strip_leading_marker(s)
    if leading_marker is not None:
        rest, kind = leading_marker
        _apply_found(state, kind)
        return rest
    trailing_marker = _strip_trailing_marker(s)
    if trailing_marker is not None:
        rest, kind = trailing_marker
        _apply_found(state, kind)
        return rest
    return s


_MAX_STRIP_ITERATIONS = 10


def _decide_decimal_separator(s: str) -> str | None:
    """Return '.' or ',' if that's the decimal separator, or None for none.

    Implements the generic disambiguation rules from the task spec: when
    both '.' and ',' appear, the rightmost is the decimal separator; when
    only one kind appears, 1-2 trailing digits means decimal, 3 trailing
    digits means thousands -- except a lone '.' followed by exactly 3
    digits is treated as a decimal point with too many decimal places
    (rejected downstream), since '.' is the conventional decimal symbol
    and only ',' defaults to a thousands reading in that single-occurrence,
    3-trailing-digit case.
    """
    dot_count = s.count(".")
    comma_count = s.count(",")

    if dot_count > 0 and comma_count > 0:
        return "." if s.rfind(".") > s.rfind(",") else ","

    if dot_count == 0 and comma_count == 0:
        return None

    sep = "." if dot_count > 0 else ","
    count = dot_count if dot_count > 0 else comma_count
    trailing = s[s.rfind(sep) + 1 :]
    if not trailing.isdigit():
        raise ParseError("unrecognized characters in amount")

    if count == 1:
        if len(trailing) in (1, 2):
            return sep
        if len(trailing) == 3:
            return None if sep == "," else sep
        raise ParseError("inconsistent digit grouping in amount")

    # Multiple occurrences of the same separator: only a thousands-grouping
    # reading is possible (a number can have at most one decimal point).
    if len(trailing) != 3:
        raise ParseError("inconsistent digit grouping in amount")
    return None


def _split_and_validate_groups(integer_part: str, thousands_chars: frozenset[str]) -> str:
    if not integer_part:
        return "0"
    pattern = "[" + "".join(re.escape(c) for c in thousands_chars) + "]"
    groups = re.split(pattern, integer_part)
    if any(not g or not g.isdigit() for g in groups):
        raise ParseError("inconsistent digit grouping in amount")
    if len(groups) > 1:
        first, rest = groups[0], groups[1:]
        if not (1 <= len(first) <= 3):
            raise ParseError("inconsistent digit grouping in amount")
        if any(len(g) != 3 for g in rest):
            raise ParseError("inconsistent digit grouping in amount")
    return "".join(groups)


def interpret_amount(raw: str) -> PrintedAmount:
    """Interpret one printed amount string, generically, for any issuer.

    Handles a leading/trailing currency symbol or 3-letter ISO code, a
    textual ``CR``/``DR``/``DB`` marker, a sign (leading minus/en-dash/
    minus-sign, trailing hyphen, or wrapping parentheses), and either comma
    or dot as the decimal separator with the other (plus space/NBSP/
    thin-space/apostrophe variants) as thousands grouping. Raises
    ``ParseError`` -- without echoing the raw text, since this is financial
    data (AGENTS.md §3) -- for anything it can't confidently interpret.

    A textual ``debit`` marker together with a sign (e.g. "-12.00 DR") is
    rejected as contradictory: text says money owed, the sign says
    negative. A textual ``credit`` marker together with a sign is *not*
    rejected -- both point the same direction (e.g. "(12.00) CR" is just a
    redundant way of printing a credit), so there's nothing to contradict.
    """
    s = raw.strip()
    if not s:
        raise ParseError("amount is empty")

    state = _MarkerState()

    for _ in range(_MAX_STRIP_ITERATIONS):
        new_s = _strip_tokens(s, state)
        if new_s == s:
            break
        s = new_s
    else:  # pragma: no cover - defensive; real inputs converge in a few passes
        raise ParseError("unrecognized characters in amount")

    if state.marker == "debit" and state.negative:
        raise ParseError("conflicting sign and debit marker in amount")

    if not s or any(ch not in _ALLOWED_NUMERAL_CHARS for ch in s):
        raise ParseError("unrecognized characters in amount")

    decimal_sep = _decide_decimal_separator(s)

    if decimal_sep is None:
        integer_part_raw = s
        decimal_part = "00"
    else:
        idx = s.rfind(decimal_sep)
        integer_part_raw = s[:idx]
        raw_decimal = s[idx + 1 :]
        if not raw_decimal.isdigit() or len(raw_decimal) not in (1, 2):
            if len(raw_decimal) > 2:
                raise ParseError("amount has more than 2 decimal places")
            raise ParseError("unrecognized characters in amount")
        decimal_part = raw_decimal.ljust(2, "0")

    thousands_chars = _THOUSANDS_ONLY_CHARS | (
        _DOT_COMMA - ({decimal_sep} if decimal_sep else set())
    )
    integer_digits = _split_and_validate_groups(integer_part_raw, thousands_chars)

    magnitude = Decimal(f"{integer_digits}.{decimal_part}")
    return PrintedAmount(magnitude=magnitude, marker=state.marker, negative=state.negative)
