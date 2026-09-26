"""load -> extract -> normalize -> validate, with one retry on mismatch.

The model reads; code decides (AGENTS.md). A validation ``FAILED`` never
raises here -- it is a legitimate outcome the caller (e.g. an API endpoint
that flags the statement for manual review) decides what to do with. Nor
does a normalization failure (an amount that can't be read as a number)
raise: it gets the same one retry, and if it still can't be normalized the
statement is recorded FAILED with zero transactions rather than surfacing
as an upload error with nothing recorded at all.
"""

import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from finagent.core.errors import ParseError
from finagent.domain.models import AccountType, ParsedStatement
from finagent.ingest.extract.base import StatementExtractor
from finagent.ingest.extract.schema import StatementExtraction
from finagent.ingest.loaders import load_document
from finagent.ingest.normalize import normalize, normalize_issuer, normalize_last4, parse_iso_date
from finagent.ingest.validate import ValidationResult, ValidationStatus, validate

logger = logging.getLogger(__name__)

_UNNORMALIZABLE_PROBLEM = "an amount on the statement could not be normalized after retry"
_UNNORMALIZABLE_FEEDBACK = (
    "An amount on the statement could not be read as a number. Re-transcribe "
    "every amount exactly as printed, including any currency symbol, sign, "
    "CR/DR marker, or parentheses."
)


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

    Retries extraction once when the first attempt either (a) fails
    reconciliation with a known numeric discrepancy, feeding that back, or
    (b) can't even be normalized (an unparseable amount), feeding back a
    request to re-transcribe. A ``FAILED`` result with no numeric
    discrepancy and no normalization error (e.g. zero transactions, or
    dates outside the statement period) is not retried, since there is
    nothing concrete to feed back to the model.
    """
    doc = load_document(filename, data)

    extraction = extractor.extract(doc)
    statement, result = _normalize_and_validate(extraction)
    attempts = 1

    if statement is None or (
        result.status is ValidationStatus.FAILED and result.discrepancy is not None
    ):
        feedback = (
            _UNNORMALIZABLE_FEEDBACK
            if statement is None
            else _retry_feedback(statement, result.discrepancy)  # type: ignore[arg-type]
        )
        extraction = extractor.extract(doc, feedback=feedback)
        statement, result = _normalize_and_validate(extraction)
        attempts = 2

    if statement is None:
        statement = _empty_statement(extraction)

    return ExtractionResult(
        statement=statement,
        status=result.status,
        problems=result.problems,
        attempts=attempts,
        extraction=extraction,
    )


def _normalize_and_validate(
    extraction: StatementExtraction,
) -> tuple[ParsedStatement | None, ValidationResult]:
    """``normalize`` + ``validate``, turning a ``ParseError`` into a FAILED result.

    Returns ``(None, <FAILED result>)`` when normalization itself fails, so
    the caller knows a normalization retry (rather than a discrepancy retry)
    is what's needed.
    """
    try:
        statement = normalize(extraction)
    except ParseError:
        return None, ValidationResult(
            status=ValidationStatus.FAILED, problems=(_UNNORMALIZABLE_PROBLEM,)
        )
    return statement, validate(extraction, statement)


def _empty_statement(extraction: StatementExtraction) -> ParsedStatement:
    """A zero-transaction ``ParsedStatement`` for a FAILED, unnormalizable result.

    Keeps account identity and period where they're parseable without any
    amount parsing, since only amounts (never issuer/last4/type/dates) can
    raise here.
    """
    return ParsedStatement(
        issuer=extraction.issuer,
        account_name=extraction.account_name,
        account_label=(
            f"{normalize_issuer(extraction.issuer)} ****{normalize_last4(extraction.account_last4)}"
        ),
        account_type=AccountType(extraction.account_type),
        currency=extraction.currency,
        period_start=_try_parse_date(extraction.period_start),
        period_end=_try_parse_date(extraction.period_end),
        transactions=(),
    )


def _try_parse_date(raw: str | None) -> date | None:
    if raw is None:
        return None
    try:
        return parse_iso_date(raw)
    except ParseError:
        return None


def _retry_feedback(statement: ParsedStatement, discrepancy: Decimal) -> str:
    total = sum((tx.amount for tx in statement.transactions), Decimal("0"))
    expected = total - discrepancy
    return (
        f"Your transactions sum to {total} but the printed totals imply {expected} "
        f"(difference {discrepancy}). Re-check for missed, duplicated, or mis-directed lines "
        "and return the complete corrected extraction."
    )
