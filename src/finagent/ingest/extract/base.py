"""Extraction backend contract.

LLM access goes only through this Protocol (AGENTS.md §3): tests use fakes,
and no test ever calls the real API. The Anthropic implementation lives in
``finagent.ingest.extract.anthropic``.
"""

from collections.abc import Sequence
from typing import Protocol

from finagent.domain.models import KnownAccount
from finagent.ingest.document import SourceDocument
from finagent.ingest.extract.schema import StatementExtraction


class StatementExtractor(Protocol):
    """Reads a statement document and returns a structured transcription."""

    def extract(
        self,
        doc: SourceDocument,
        feedback: str | None = None,
        known_accounts: Sequence[KnownAccount] = (),
    ) -> StatementExtraction:
        """Extract a statement into a ``StatementExtraction``.

        ``feedback`` carries a discrepancy description from a failed
        validation of a previous attempt (see ``ingest.pipeline``), asking
        the model to re-check and return a corrected, complete extraction.
        ``known_accounts`` lists accounts already on record, so the model
        can return the exact issuer name already on file when this
        statement matches one by last 4 digits and account type, instead of
        drifting (e.g. "TD" vs "TD BANK") into what looks like a new
        account.
        """
        ...
