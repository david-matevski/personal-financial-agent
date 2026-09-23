"""Statement parser contract.

One parser module per issuer (e.g. ``amex.py``, ``cibc.py``, ``td.py``), each
implementing this Protocol. Adding an issuer must not require editing
another issuer's parser (AGENTS.md §3).
"""

from typing import Protocol

from finagent.domain.models import Issuer, ParsedStatement
from finagent.ingest.document import SourceDocument


class StatementParser(Protocol):
    """Recognizes and parses statements for one issuer and format."""

    issuer: Issuer

    def can_parse(self, doc: SourceDocument) -> bool:
        """Return True if this parser recognizes the document's layout.

        Must be cheap and must not raise: check the document kind and a few
        identifying markers only.
        """
        ...

    def parse(self, doc: SourceDocument) -> ParsedStatement:
        """Parse the document into a ParsedStatement.

        Parsers reconcile extracted transactions against the statement's own
        totals where the statement provides them, and raise
        ``finagent.core.errors.ParseError`` on mismatch rather than returning
        partial data.
        """
        ...
