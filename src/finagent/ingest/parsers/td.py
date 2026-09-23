"""TD credit card PDF statement parser (AGENTS.md ingest/parsers/td.py).

Parses TD Visa credit card statements that arrive as a text-layer ``TEXT``
``SourceDocument`` (one string per PDF page, extracted with
``page.extract_text(x_tolerance=1)``). Layout notes:

- Page 1 carries the header (product name, masked card number, statement
  date/period) and the ``TRANSACTION POSTING`` / ``DATE DATE ACTIVITY
  DESCRIPTION AMOUNT($)`` column header.
- Each transaction is one line: ``MON D MON D DESCRIPTION $AMOUNT``
  (transaction date, posting date, description, amount; credits print as
  ``-$AMOUNT``). TD interleaves a right-hand info panel (points earned,
  payment info, interest rates, ...) on the *same line* after the amount,
  and on some following lines (foreign-currency detail, wrapped
  descriptions) with no leading date pair. Matching only lines that start
  with two ``MON D`` date pairs, and taking the first ``$amount`` after the
  description, naturally ignores all of that.
- Transaction dates carry no year; the year is inferred from the
  statement period, which does carry full years and may itself cross a
  December/January boundary.
- Transactions can continue on later pages; pages of pure legal text have
  none. The statement's own totals (``PREVIOUS STATEMENT BALANCE`` /
  ``NEW BALANCE`` or ``TOTAL NEW BALANCE`` on the last transaction page)
  are used to reconcile the parsed transactions.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal

from finagent.core.errors import ParseError
from finagent.domain.hashing import assign_row_sequences
from finagent.domain.models import AccountType, Issuer, ParsedStatement, Transaction
from finagent.ingest.document import DocumentKind, SourceDocument

_MONTHS = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}

_PRODUCT_RE = re.compile(r"^(TD [A-Za-z ]*?Visa[A-Za-z ]*?)\*?$")
_CARD_RE = re.compile(r"\d{4}\s+\d{2}X{2}\s+X{4}\s+(\d{4})")
_PERIOD_RE = re.compile(
    r"STATEMENT PERIOD:\s*([A-Za-z]+ \d{1,2}, \d{4})\s+to\s+([A-Za-z]+ \d{1,2}, \d{4})"
)
_PREVIOUS_BALANCE_RE = re.compile(r"PREVIOUS STATEMENT BALANCE\s+\$([\d,]+\.\d{2})")
_NEW_BALANCE_RE = re.compile(r"(?:TOTAL )?NEW BALANCE\s+\$([\d,]+\.\d{2})")
_TX_LINE_RE = re.compile(
    r"^(?P<tmon>[A-Z]{3})\s+(?P<tday>\d{1,2})\s+"
    r"(?P<pmon>[A-Z]{3})\s+(?P<pday>\d{1,2})\s+"
    r"(?P<desc>.+?)\s+(?P<amount>-?\$[\d,]+\.\d{2})"
)
_WHITESPACE_RE = re.compile(r"\s+")


def _parse_amount(raw: str) -> Decimal:
    """Parse a statement amount like ``$1,234.56`` or ``-$260.32``."""
    return Decimal(raw.replace("$", "").replace(",", ""))


def _safe_date(year: int, month: int, day: int) -> date | None:
    """Build a date, returning None instead of raising on an invalid one."""
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _infer_date(month: int, day: int, period_end: date) -> date:
    """Infer the calendar year for a bare month/day within a statement period.

    No statement line is ever dated after its own period end, so we anchor
    on ``period_end.year``: if the date built with that year would fall
    after ``period_end`` (e.g. a December transaction line under a
    January-to-February period), it actually belongs to the previous year.
    This is correct whether or not the period itself crosses a December/
    January boundary, unlike inferring from ``period_start``, which gets a
    non-crossing period's pre-period-start dates (e.g. a late-December
    transaction date posting in early January) wrong.

    Guards Feb 29: if the date is invalid in the anchor year, falls back to
    the previous year; raises ``ParseError`` if it is invalid in both.
    """
    primary = _safe_date(period_end.year, month, day)
    if primary is not None and primary <= period_end:
        return primary
    secondary = _safe_date(period_end.year - 1, month, day)
    if secondary is not None:
        return secondary
    if primary is not None:
        return primary
    raise ParseError(f"TD statement has an invalid date: month={month} day={day}")


class TdCreditPdfParser:
    """Parses TD Visa credit card PDF statements (text layer)."""

    issuer = Issuer.TD

    def can_parse(self, doc: SourceDocument) -> bool:
        if doc.kind is not DocumentKind.TEXT or not doc.pages:
            return False
        first_page = doc.pages[0]
        has_td = "TD" in first_page and ("Visa" in first_page or "TD CANADA TRUST" in first_page)
        has_header = (
            "TRANSACTION" in first_page
            and "POSTING" in first_page
            and "ACTIVITY DESCRIPTION" in first_page
        )
        return has_td and has_header

    def parse(self, doc: SourceDocument) -> ParsedStatement:
        if not doc.pages:
            raise ParseError("TD statement has no pages")

        first_page = doc.pages[0]
        product, last4 = self._extract_header(first_page)
        period_start, period_end = self._extract_period(first_page)
        account_label = f"{product} ****{last4}"

        transactions = self._extract_transactions(doc.pages, period_end, account_label)

        full_text = "\n".join(doc.pages)
        previous_balance, new_balance = self._extract_totals(full_text)
        total = sum((tx.amount for tx in transactions), Decimal("0"))
        expected = new_balance - previous_balance
        if total != expected:
            raise ParseError(
                "TD statement did not reconcile: transactions summed to "
                f"{total}, expected {expected}"
            )

        transactions = assign_row_sequences(transactions)
        return ParsedStatement(
            issuer=Issuer.TD,
            account_label=account_label,
            period_start=period_start,
            period_end=period_end,
            transactions=tuple(transactions),
        )

    def _extract_header(self, first_page: str) -> tuple[str, str]:
        card_match = _CARD_RE.search(first_page)
        if card_match is None:
            raise ParseError("TD statement is missing the masked card number")
        last4 = card_match.group(1)

        product = None
        for line in first_page.splitlines():
            product_match = _PRODUCT_RE.match(line.strip())
            if product_match is not None:
                product = product_match.group(1).strip()
                break
        if product is None:
            raise ParseError("TD statement is missing the product name")
        return product, last4

    def _extract_period(self, first_page: str) -> tuple[date, date]:
        period_match = _PERIOD_RE.search(first_page)
        if period_match is None:
            raise ParseError("TD statement is missing the statement period")
        period_start = datetime.strptime(period_match.group(1), "%B %d, %Y").date()
        period_end = datetime.strptime(period_match.group(2), "%B %d, %Y").date()
        return period_start, period_end

    def _extract_transactions(
        self,
        pages: tuple[str, ...],
        period_end: date,
        account_label: str,
    ) -> list[Transaction]:
        transactions: list[Transaction] = []
        for page in pages:
            for line in page.splitlines():
                match = _TX_LINE_RE.match(line.strip())
                if match is None:
                    continue
                tmon, pmon = match.group("tmon"), match.group("pmon")
                if tmon not in _MONTHS or pmon not in _MONTHS:
                    continue
                transaction_date = _infer_date(_MONTHS[tmon], int(match.group("tday")), period_end)
                posted_date = _infer_date(_MONTHS[pmon], int(match.group("pday")), period_end)
                description = _WHITESPACE_RE.sub(" ", match.group("desc")).strip()
                amount = _parse_amount(match.group("amount"))
                transactions.append(
                    Transaction(
                        issuer=Issuer.TD,
                        account_type=AccountType.CREDIT,
                        account_label=account_label,
                        posted_date=posted_date,
                        transaction_date=transaction_date,
                        description=description,
                        amount=amount,
                    )
                )
        return transactions

    def _extract_totals(self, full_text: str) -> tuple[Decimal, Decimal]:
        previous_match = _PREVIOUS_BALANCE_RE.search(full_text)
        new_matches = _NEW_BALANCE_RE.findall(full_text)
        if previous_match is None or not new_matches:
            raise ParseError("TD statement is missing balance totals")
        previous_balance = _parse_amount(previous_match.group(1))
        new_balance = _parse_amount(new_matches[-1])
        return previous_balance, new_balance
