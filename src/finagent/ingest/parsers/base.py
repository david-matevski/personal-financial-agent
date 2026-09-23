"""Statement parser contract.

One parser module per issuer (e.g. ``amex.py``, ``cibc.py``, ``td.py``), each
implementing this Protocol. Adding an issuer must not require editing
another issuer's parser (AGENTS.md §3).
"""

from typing import Protocol

from finagent.domain.models import Issuer, ParsedStatement


class StatementParser(Protocol):
    """Recognizes and parses statements for one issuer."""

    issuer: Issuer

    def can_parse(self, pages: list[str]) -> bool:
        """Return True if this parser recognizes the statement layout."""
        ...

    def parse(self, pages: list[str]) -> ParsedStatement:
        """Parse extracted page text into a ParsedStatement.

        Raises ``finagent.core.errors.ParseError`` if the statement is
        recognized but cannot be parsed.
        """
        ...
