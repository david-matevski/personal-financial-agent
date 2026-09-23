"""load -> extract -> normalize -> validate, with one retry on mismatch.

The model reads; code decides (AGENTS.md). A validation ``FAILED`` never
raises here -- it is a legitimate outcome the caller (e.g. an API endpoint
that flags the statement for manual review) decides what to do with.
"""

import logging
from dataclasses import dataclass
from decimal import Decimal

from finagent.domain.models import ParsedStatement
from finagent.ingest.extract.base import StatementExtractor
from finagent.ingest.extract.schema import StatementExtraction
from finagent.ingest.loaders import load_document
from finagent.ingest.normalize import normalize
from finagent.ingest.validate import ValidationStatus, validate

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExtractionResult:
    """The outcome of running one statement through the full pipeline."""

    statement: ParsedStatement
    status: ValidationStatus
    problems: tuple[str, ...]
    attempts: int
    extraction: StatementExtraction
    """The raw (last-attempt) model transcription, kept for persistence/audit.

    Callers that need fields ``ParsedStatement`` doesn't carry (e.g.
    ``account_last4``, printed totals as strings) read them from here rather
    than from the normalized statement.
    """


def extract_statement(
    filename: str, data: bytes, extractor: StatementExtractor
) -> ExtractionResult:
    """Run one statement through load -> extract -> normalize -> validate.

    Retries extraction once -- feeding back the validation discrepancy --
    when the first attempt fails reconciliation with a known numeric
    discrepancy. A ``FAILED`` result with no numeric discrepancy (e.g. zero
    transactions, or dates outside the statement period) is not retried,
    since there is nothing concrete to feed back to the model.
    """
    doc = load_document(filename, data)

    extraction = extractor.extract(doc)
    statement = normalize(extraction)
    result = validate(extraction, statement)
    attempts = 1

    if result.status is ValidationStatus.FAILED and result.discrepancy is not None:
        feedback = _retry_feedback(statement, result.discrepancy)
        extraction = extractor.extract(doc, feedback=feedback)
        statement = normalize(extraction)
        result = validate(extraction, statement)
        attempts = 2

    return ExtractionResult(
        statement=statement,
        status=result.status,
        problems=result.problems,
        attempts=attempts,
        extraction=extraction,
    )


def _retry_feedback(statement: ParsedStatement, discrepancy: Decimal) -> str:
    total = sum((tx.amount for tx in statement.transactions), Decimal("0"))
    expected = total - discrepancy
    return (
        f"Your transactions sum to {total} but the printed totals imply {expected} "
        f"(difference {discrepancy}). Re-check for missed, duplicated, or mis-directed lines "
        "and return the complete corrected extraction."
    )
