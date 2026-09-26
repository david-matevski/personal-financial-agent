"""Tests for finagent.db.repository.save_extraction against a real Postgres."""

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from finagent.db.models import Account, Category, Statement
from finagent.db.models import Transaction as TransactionRow
from finagent.db.repository import save_extraction
from finagent.ingest.extract.schema import StatementExtraction
from finagent.ingest.normalize import normalize
from finagent.ingest.pipeline import ExtractionResult
from finagent.ingest.validate import validate

_ACCOUNT_KW: dict[str, object] = {
    "issuer": "TD",
    "account_name": "TD Rewards Visa",
    "account_last4": "1234",
    "account_type": "CREDIT",
    "currency": "CAD",
}


def _extraction(**overrides: object) -> StatementExtraction:
    defaults: dict[str, object] = {
        **_ACCOUNT_KW,
        "period_start": "2026-01-01",
        "period_end": "2026-01-31",
        "opening_balance": "100.00",
        "closing_balance": "108.00",
        "total_money_out": None,
        "total_money_in": None,
        "transactions": [
            {
                "posted_date": "2026-01-05",
                "description": "Fictional Coffee Co",
                "amount": "5.00",
                "direction": "OUT",
            },
            {
                "posted_date": "2026-01-06",
                "description": "Fictional Grocer",
                "amount": "3.00",
                "direction": "OUT",
            },
        ],
    }
    defaults.update(overrides)
    return StatementExtraction.model_validate(defaults)


def _result(extraction: StatementExtraction, attempts: int = 1) -> ExtractionResult:
    statement = normalize(extraction)
    outcome = validate(extraction, statement)
    return ExtractionResult(
        statement=statement,
        status=outcome.status,
        problems=outcome.problems,
        attempts=attempts,
        extraction=extraction,
    )


def _save(session: Session, extraction: StatementExtraction, *, sha: str, filename: str = "a.csv"):
    result = _result(extraction)
    saved = save_extraction(
        session,
        filename=filename,
        file_sha256=sha,
        media_type="text/csv",
        result=result,
        extraction_json=extraction.model_dump(),
        model="claude-opus-5-5",
    )
    session.commit()
    return saved


def test_first_save_inserts_account_statement_and_transactions(session: Session) -> None:
    extraction = _extraction()
    sha = "a" * 64

    saved = _save(session, extraction, sha=sha)

    assert saved.already_imported is False
    assert saved.transactions_inserted == 2
    assert saved.transactions_skipped_duplicate == 0
    assert saved.status.value == "VERIFIED"

    accounts = session.execute(select(Account)).scalars().all()
    assert len(accounts) == 1
    assert accounts[0].issuer == "TD"
    assert accounts[0].account_last4 == "1234"

    statement = session.get(Statement, saved.statement_id)
    assert statement is not None
    assert statement.account_id == accounts[0].id
    assert statement.transactions_inserted == 2
    assert statement.file_sha256 == sha

    tx_count = session.execute(select(func.count()).select_from(TransactionRow)).scalar_one()
    assert tx_count == 2


def test_resave_same_file_is_a_noop(session: Session) -> None:
    extraction = _extraction()
    sha = "b" * 64

    first = _save(session, extraction, sha=sha)
    second = _save(session, extraction, sha=sha)

    assert second.already_imported is True
    assert second.statement_id == first.statement_id

    statement_count = session.execute(select(func.count()).select_from(Statement)).scalar_one()
    assert statement_count == 1


def test_overlapping_statement_skips_duplicate_transactions_by_hash(session: Session) -> None:
    first_extraction = _extraction()
    _save(session, first_extraction, sha="c" * 64, filename="jan.csv")

    # A second, overlapping statement: same account, one repeated line plus
    # one genuinely new one.
    second_extraction = _extraction(
        period_start="2026-01-01",
        period_end="2026-02-05",
        opening_balance="100.00",
        closing_balance="111.00",
        transactions=[
            {
                "posted_date": "2026-01-05",
                "description": "Fictional Coffee Co",
                "amount": "5.00",
                "direction": "OUT",
            },
            {
                "posted_date": "2026-01-06",
                "description": "Fictional Grocer",
                "amount": "3.00",
                "direction": "OUT",
            },
            {
                "posted_date": "2026-02-01",
                "description": "Fictional Streaming Co",
                "amount": "3.00",
                "direction": "OUT",
            },
        ],
    )
    saved = _save(session, second_extraction, sha="d" * 64, filename="feb.csv")

    assert saved.transactions_inserted == 1
    assert saved.transactions_skipped_duplicate == 2

    tx_count = session.execute(select(func.count()).select_from(TransactionRow)).scalar_one()
    assert tx_count == 3


def test_failed_result_stores_statement_with_no_transactions(session: Session) -> None:
    extraction = _extraction(
        opening_balance=None,
        closing_balance=None,
        total_money_out=None,
        total_money_in=None,
        transactions=[],
    )
    saved = _save(session, extraction, sha="e" * 64)

    assert saved.status.value == "FAILED"
    assert saved.transactions_inserted == 0

    statement = session.get(Statement, saved.statement_id)
    assert statement is not None
    assert statement.account_id is None
    assert statement.extraction["issuer"] == "TD"

    tx_count = session.execute(select(func.count()).select_from(TransactionRow)).scalar_one()
    assert tx_count == 0


def test_categories_seed_has_15_rows(session: Session) -> None:
    count = session.execute(select(func.count()).select_from(Category)).scalar_one()
    assert count == 15


def test_reimport_updates_account_name_to_latest(session: Session) -> None:
    _save(session, _extraction(account_name="Old Name"), sha="f" * 64, filename="one.csv")
    _save(session, _extraction(account_name="New Name"), sha="g" * 64, filename="two.csv")

    accounts = session.execute(select(Account)).scalars().all()
    assert len(accounts) == 1
    assert accounts[0].account_name == "New Name"


def test_money_columns_are_decimal(session: Session) -> None:
    saved = _save(session, _extraction(), sha="h" * 64)
    statement = session.get(Statement, saved.statement_id)
    assert statement is not None
    assert statement.opening_balance == Decimal("100.00")
    assert statement.closing_balance == Decimal("108.00")


def test_issuer_and_last4_variants_map_to_one_account(session: Session) -> None:
    _save(session, _extraction(issuer="TD", account_last4="1234"), sha="a" * 64)
    _save(session, _extraction(issuer=" td ", account_last4="**** 1234"), sha="b" * 64)
    assert session.scalar(select(func.count()).select_from(Account)) == 1
