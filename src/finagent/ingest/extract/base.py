"""Extraction backend contract.

LLM access goes only through this Protocol (AGENTS.md §3): tests use fakes,
and no test ever calls the real API. The Anthropic implementation lives in
``finagent.ingest.extract.anthropic``.
"""

from typing import Protocol

from finagent.ingest.document import SourceDocument
from finagent.ingest.extract.schema import StatementExtraction


class StatementExtractor(Protocol):
    """Reads a statement document and returns a structured transcription."""

    def extract(self, doc: SourceDocument, feedback: str | None = None) -> StatementExtraction:
        """Extract a statement into a ``StatementExtraction``.

        ``feedback`` carries a discrepancy description from a failed
        validation of a previous attempt (see ``ingest.pipeline``), asking
        the model to re-check and return a corrected, complete extraction.
        """
        ...
