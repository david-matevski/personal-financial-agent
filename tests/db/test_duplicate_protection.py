"""Tests for near-duplicate transaction flagging (AGENTS.md task spec §5)."""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from finagent.db.models import Transaction as TransactionRow
from finagent.db.repository import (
    apply_duplicate_action,
    category_summary,
    list_transactions,
    save_extraction,
)
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
        "closing_balance": "105.00",
        "total_money_out": None,
        "total_money_in": None,
        "transactions": [
            {
                "posted_date": "2026-01-05",
                "description": "Fictional Coffee Co #1234",
                "amount": "5.00",
                "direction": "OUT",
            }
        ],
    }
    defaults.update(overrides)
    return StatementExtraction.model_validate(defaults)


def _save(session: Session, extraction: StatementExtraction, *, sha: str, filename: str = "a.csv"):
    statement = normalize(extraction)
    outcome = validate(extraction, statement)
    result = ExtractionResult(
        statement=statement,
        status=outcome.status,
        problems=outcome.problems,
        attempts=1,
        extraction=extraction,
    )
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


def _two_statements_with_near_duplicate(session: Session) -> tuple[int, int]:
    """Same purchase, imported twice with a shifted date and reworded description.

    Returns (original_id, duplicate_id).
    """
    first = _extraction()
    _save(session, first, sha="a" * 64, filename="jan.csv")

    second = _extraction(
        period_start="2026-01-01",
        period_end="2026-02-28",
        closing_balance="108.00",
        transactions=[
            {
                # +2 days, reformatted description -- same purchase.
                "posted_date": "2026-01-07",
                "description": "COFFEE CO 1234 TORONTO",
                "amount": "5.00",
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
    _save(session, second, sha="b" * 64, filename="feb.csv")

    rows = list(session.execute(select(TransactionRow).order_by(TransactionRow.id)).scalars().all())
    original = next(r for r in rows if r.description == "Fictional Coffee Co #1234")
    duplicate = next(r for r in rows if r.description == "COFFEE CO 1234 TORONTO")
    return original.id, duplicate.id


def test_near_duplicate_is_flagged_on_insert(session: Session) -> None:
    original_id, duplicate_id = _two_statements_with_near_duplicate(session)

    duplicate = session.get(TransactionRow, duplicate_id)
    assert duplicate is not None
    assert duplicate.possible_duplicate_of == original_id
    assert duplicate.duplicate_reviewed is False


def test_keep_both_clears_the_flag(session: Session) -> None:
    _, duplicate_id = _two_statements_with_near_duplicate(session)

    row = apply_duplicate_action(session, duplicate_id, "keep_both")
    session.commit()

    assert row is not None
    assert row.possible_duplicate_of is None
    assert row.duplicate_reviewed is True


def test_remove_hides_from_listings_and_summary(session: Session) -> None:
    _, duplicate_id = _two_statements_with_near_duplicate(session)

    row = apply_duplicate_action(session, duplicate_id, "remove")
    session.commit()
    assert row is not None
    assert row.removed_at is not None

    visible_ids = [t.id for t in list_transactions(session, limit=100)]
    assert duplicate_id not in visible_ids

    total_count = sum(s.count for s in category_summary(session))
    all_ids = [t.id for t in list_transactions(session, limit=100, include_removed=True)]
    assert duplicate_id in all_ids
    assert total_count == len(visible_ids)


def test_restore_brings_it_back(session: Session) -> None:
    _, duplicate_id = _two_statements_with_near_duplicate(session)
    apply_duplicate_action(session, duplicate_id, "remove")
    session.commit()

    row = apply_duplicate_action(session, duplicate_id, "restore")
    session.commit()

    assert row is not None
    assert row.removed_at is None
    visible_ids = [t.id for t in list_transactions(session, limit=100)]
    assert duplicate_id in visible_ids


def test_undo_of_remove_reopens_the_duplicate_question(session: Session) -> None:
    # Regression: restore used to leave duplicate_reviewed=True, so after
    # Undo the row lost its Keep both / Remove choice entirely.
    _, duplicate_id = _two_statements_with_near_duplicate(session)
    apply_duplicate_action(session, duplicate_id, "remove")
    apply_duplicate_action(session, duplicate_id, "restore")
    session.commit()

    flagged_ids = [t.id for t in list_transactions(session, limit=100, possible_duplicates=True)]
    assert duplicate_id in flagged_ids


def test_apply_duplicate_action_unknown_id_returns_none(session: Session) -> None:
    assert apply_duplicate_action(session, 999999, "keep_both") is None


def test_apply_duplicate_action_unknown_action_raises_value_error(session: Session) -> None:
    _, duplicate_id = _two_statements_with_near_duplicate(session)
    with pytest.raises(ValueError):
        apply_duplicate_action(session, duplicate_id, "bogus")


def test_possible_duplicates_filter_matches_only_unreviewed_flags(session: Session) -> None:
    _, duplicate_id = _two_statements_with_near_duplicate(session)

    flagged = list_transactions(session, possible_duplicates=True)
    assert [t.id for t in flagged] == [duplicate_id]

    apply_duplicate_action(session, duplicate_id, "keep_both")
    session.commit()

    assert list_transactions(session, possible_duplicates=True) == []


def test_far_apart_dates_are_not_flagged(session: Session) -> None:
    first = _extraction()
    _save(session, first, sha="c" * 64, filename="jan.csv")

    far_later = _extraction(
        period_start="2026-06-01",
        period_end="2026-06-30",
        opening_balance="200.00",
        closing_balance="205.00",
        transactions=[
            {
                "posted_date": "2026-06-05",
                "description": "Fictional Coffee Co #1234",
                "amount": "5.00",
                "direction": "OUT",
            }
        ],
    )
    _save(session, far_later, sha="d" * 64, filename="june.csv")

    rows = list(session.execute(select(TransactionRow).order_by(TransactionRow.id)).scalars().all())
    assert all(r.possible_duplicate_of is None for r in rows)


def test_unrelated_description_same_amount_is_not_flagged(session: Session) -> None:
    first = _extraction()
    _save(session, first, sha="e" * 64, filename="jan.csv")

    second = _extraction(
        period_start="2026-01-01",
        period_end="2026-01-31",
        closing_balance="105.00",
        transactions=[
            {
                "posted_date": "2026-01-06",  # within 3 days
                "description": "Completely Different Merchant",
                "amount": "5.00",  # same amount
                "direction": "OUT",
            }
        ],
    )
    _save(session, second, sha="f" * 64, filename="jan2.csv")

    rows = list(session.execute(select(TransactionRow).order_by(TransactionRow.id)).scalars().all())
    assert all(r.possible_duplicate_of is None for r in rows)
