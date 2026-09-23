"""Parser for Amex "Transaction Details" XLS/XLSX exports.

Layout (verified against a real export; see AGENTS.md §6 for why no sample
data lives in this file):

    row 0: ["", "Transaction Details: ", "<card product>", ""]
    row 1: ["", "<cardholder name>", "<period start> - <period end>", ""]
    row 2: ["", "Account Number: XXX-NNNNN", "", ""]
    ... a summary block with "Last billed statement", "Charges &
        Adjustments", "Payments & Credits", and "Summary for this billed
        period:" rows, each carrying a "$"-formatted amount in the last
        column ...
    header row: ["Date", "Description", "", "Amount"]
    transaction rows: ["DD Mon. YYYY", "<description>", "", "<amount>"],
        newest first, terminated by the end of the sheet or a blank row.

Row positions are not fixed: Amex may insert or omit summary lines, so every
section is located by its label text, never by index.
"""

import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation

from finagent.core.errors import ParseError
from finagent.domain.hashing import assign_row_sequences
from finagent.domain.models import AccountType, Issuer, ParsedStatement, Transaction
from finagent.ingest.document import DocumentKind, SourceDocument

_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

_DATE_RE = re.compile(r"^(\d{1,2})\s+([A-Za-z]+)\.?\s+(\d{4})$")
_AMOUNT_RE = re.compile(r"^-?\$[\d,]+\.\d{2}$")
_WHITESPACE_RE = re.compile(r"\s+")


def _clean_product_name(raw: str) -> str:
    """Strip trademark glyphs and stray replacement/control characters.

    The exported product name (e.g. "American Express(R) Gold Rewards
    Card") carries a registered-trademark symbol that xlrd sometimes yields
    as a mojibake replacement character depending on encoding. Neither is
    meaningful for matching or display, so both are dropped.
    """
    normalized = unicodedata.normalize("NFKD", raw)
    without_symbols = "".join(
        ch for ch in normalized if unicodedata.category(ch) not in {"So", "Cn", "Cc"}
    )
    collapsed = _WHITESPACE_RE.sub(" ", without_symbols).strip()
    return collapsed


def _parse_date(raw: str) -> date:
    match = _DATE_RE.match(raw.strip())
    if not match:
        raise ParseError("unrecognized date format in Amex export")
    day_str, month_str, year_str = match.groups()
    month_key = month_str.lower().rstrip(".")
    month = _MONTHS.get(month_key)
    if month is None:
        # Tolerate abbreviations like "Sept" / "June" by prefix match.
        for key, value in _MONTHS.items():
            if month_key.startswith(key):
                month = value
                break
    if month is None:
        raise ParseError("unrecognized month name in Amex export")
    return date(int(year_str), month, int(day_str))


def _parse_amount(raw: str) -> Decimal:
    stripped = raw.strip()
    if not _AMOUNT_RE.match(stripped):
        raise ParseError("unrecognized amount format in Amex export")
    numeric = stripped.replace("$", "").replace(",", "")
    try:
        return Decimal(numeric)
    except InvalidOperation as exc:
        raise ParseError("unparseable amount in Amex export") from exc


def _find_row(rows: tuple[tuple[str, ...], ...], label: str, *, column: int = 0) -> int:
    for index, row in enumerate(rows):
        if column < len(row) and row[column].strip().lower().startswith(label.lower()):
            return index
    raise ParseError(f"could not locate '{label}' row in Amex export")


def _row_amount(row: tuple[str, ...]) -> Decimal:
    for cell in reversed(row):
        if cell.strip():
            return _parse_amount(cell)
    raise ParseError("summary row has no amount")


class AmexExportParser:
    """Parses Amex "Transaction Details" spreadsheet exports."""

    issuer = Issuer.AMEX

    def can_parse(self, doc: SourceDocument) -> bool:
        if doc.kind is not DocumentKind.TABLE:
            return False
        header_text = " ".join(cell for row in doc.rows[:3] for cell in row)
        return "Transaction Details" in header_text and "American Express" in header_text

    def parse(self, doc: SourceDocument) -> ParsedStatement:
        rows = doc.rows

        product_row_idx = _find_row(rows, "Transaction Details", column=1)
        product_row = rows[product_row_idx]
        product = _clean_product_name(product_row[2]) if len(product_row) > 2 else ""

        period_row_idx = product_row_idx + 1
        if period_row_idx >= len(rows) or len(rows[period_row_idx]) < 3:
            raise ParseError("missing statement period row in Amex export")
        period_start, period_end = self._parse_period(rows[period_row_idx][2])

        account_row_idx = _find_row(rows, "Account Number", column=1)
        account_number = rows[account_row_idx][1]
        last_digits = re.sub(r"\D", "", account_number)[-4:]
        account_label = f"{product} ****{last_digits}"

        last_billed_idx = _find_row(rows, "Last billed statement")
        charges_idx = _find_row(rows, "Charges & Adjustments")
        payments_idx = _find_row(rows, "Payments & Credits")
        summary_idx = _find_row(rows, "Summary for this billed period")

        last_billed = _row_amount(rows[last_billed_idx])
        charges = _row_amount(rows[charges_idx])
        payments = _row_amount(rows[payments_idx])
        summary_total = _row_amount(rows[summary_idx])

        header_idx = _find_row(rows, "Date", column=0)

        transactions_newest_first: list[Transaction] = []
        running_total = Decimal("0")
        for row in rows[header_idx + 1 :]:
            if not any(cell.strip() for cell in row):
                break
            if len(row) < 4:
                raise ParseError("malformed transaction row in Amex export")
            posted_date = _parse_date(row[0])
            description = _WHITESPACE_RE.sub(" ", row[1]).strip()
            amount = _parse_amount(row[3])
            running_total += amount
            transactions_newest_first.append(
                Transaction(
                    issuer=Issuer.AMEX,
                    account_type=AccountType.CREDIT,
                    account_label=account_label,
                    posted_date=posted_date,
                    transaction_date=None,
                    description=description,
                    amount=amount,
                )
            )

        if running_total != charges - payments:
            raise ParseError("Amex export transactions do not sum to charges minus payments")
        if last_billed + running_total != summary_total:
            raise ParseError(
                "Amex export last billed balance plus transactions does not match "
                "the billed period summary"
            )

        # Rows arrive newest-first; reverse to chronological order for output
        # and hash assignment. Reversal is deterministic for a fixed input
        # file, so re-importing the same export yields the same
        # row_sequence values (and therefore the same dedup hashes) every
        # time. It does invert the relative order of same-day duplicate
        # lines (e.g. two identical coffee charges), so row_sequence for
        # such a pair is stable only as long as Amex does not itself
        # reorder same-day duplicates between exports of the same period.
        transactions = list(reversed(transactions_newest_first))
        transactions = assign_row_sequences(transactions)

        return ParsedStatement(
            issuer=Issuer.AMEX,
            account_label=account_label,
            period_start=period_start,
            period_end=period_end,
            transactions=tuple(transactions),
        )

    @staticmethod
    def _parse_period(raw: str) -> tuple[date, date]:
        parts = raw.split(" - ")
        if len(parts) != 2:
            raise ParseError("unrecognized statement period format in Amex export")
        start_raw, end_raw = parts
        return _parse_date(start_raw), _parse_date(end_raw)
