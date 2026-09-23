"""Structured-output schema for statement extraction.

The model transcribes only -- every field here is either a verbatim string
(amounts and dates as printed) or a closed enum-like literal the model
reports directly from the page (direction, account type). Code does all
arithmetic and sign interpretation in ``finagent.ingest.normalize``
(AGENTS.md §3: "The LLM transcribes, code interprets").
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ExtractedTransaction(BaseModel):
    """One transaction line, transcribed verbatim from the statement."""

    model_config = ConfigDict(extra="forbid")

    transaction_date: str | None = None
    posted_date: str
    description: str
    amount: str
    direction: Literal["OUT", "IN"]
    running_balance: str | None = None


class StatementExtraction(BaseModel):
    """The full transcription of one statement document."""

    model_config = ConfigDict(extra="forbid")

    issuer: str
    account_name: str
    account_last4: str
    account_type: Literal["CREDIT", "DEBIT"]
    currency: str
    period_start: str | None = None
    period_end: str | None = None
    opening_balance: str | None = None
    closing_balance: str | None = None
    total_money_out: str | None = None
    total_money_in: str | None = None
    transactions: list[ExtractedTransaction] = Field(default_factory=list)
