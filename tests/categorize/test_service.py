"""DB-backed tests for categorize_transactions (skip if no Postgres)."""

from collections.abc import Sequence
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from finagent.categorize.base import (
    CategorizeItem,
    CategoryDecision,
    CategoryExample,
    CategoryOption,
)
from finagent.categorize.service import categorize_transactions
from finagent.db.models import Account, Category, Statement
from finagent.db.models import Transaction as TransactionRow
from tests.categorize.helpers import FakeCategorizer

_HASH_COUNTER = iter(range(1_000_000))


def _account(session: Session, *, last4: str = "1234") -> Account:
    account = Account(
        issuer="TD",
        account_last4=last4,
        account_type="CREDIT",
        account_name="TD Rewards Visa",
        currency="CAD",
        label="TD Rewards Visa ...1234",
    )
    session.add(account)
    session.flush()
    return account


def _statement(session: Session, *, sha_suffix: str) -> Statement:
    statement = Statement(
        filename="a.csv",
        file_sha256=(sha_suffix * 64)[:64],
        status="VERIFIED",
        attempts=1,
        problems=[],
        extraction={},
        model="test",
    )
    session.add(statement)
    session.flush()
    return statement


def _transaction(
    session: Session,
    *,
    account: Account,
    statement: Statement,
    description: str = "Fictional Coffee Co",
    amount: Decimal = Decimal("5.00"),
    category_id: int | None = None,
    category_source: str | None = None,
    category_confidence: Decimal | None = None,
    categorized_at: datetime | None = None,
) -> TransactionRow:
    row = TransactionRow(
        account_id=account.id,
        statement_id=statement.id,
        transaction_hash=f"{next(_HASH_COUNTER):064d}",
        posted_date=date(2026, 1, 5),
        description=description,
        amount=amount,
        currency="CAD",
        row_sequence=0,
        category_id=category_id,
        category_source=category_source,
        category_confidence=category_confidence,
        categorized_at=categorized_at,
    )
    session.add(row)
    session.flush()
    return row


def _categories(session: Session) -> list[Category]:
    return list(session.execute(select(Category).order_by(Category.id)).scalars().all())


def test_categorizes_uncategorized_rows(session: Session) -> None:
    account = _account(session)
    statement = _statement(session, sha_suffix="a")
    row = _transaction(session, account=account, statement=statement)
    session.commit()
    categorizer = FakeCategorizer(confidence=Decimal("0.900"))

    updated = categorize_transactions(session, categorizer)
    session.commit()

    assert updated == 1
    session.expire_all()
    refreshed = session.get(TransactionRow, row.id)
    assert refreshed is not None
    assert refreshed.category_id is not None
    assert refreshed.category_source == "ai"
    assert refreshed.category_confidence == Decimal("0.900")
    assert refreshed.categorized_at is not None


def test_never_overwrites_a_user_categorized_row(session: Session) -> None:
    account = _account(session)
    statement = _statement(session, sha_suffix="b")
    # Defensive case: category_id NULL (so it'd normally be picked up) but
    # already marked category_source='user' -- must still never be touched.
    row = _transaction(session, account=account, statement=statement, category_source="user")
    session.commit()
    categorizer = FakeCategorizer()

    updated = categorize_transactions(session, categorizer)
    session.commit()

    assert updated == 0
    session.expire_all()
    refreshed = session.get(TransactionRow, row.id)
    assert refreshed is not None
    assert refreshed.category_id is None
    assert refreshed.category_source == "user"


def test_transaction_ids_filter_excludes_other_uncategorized_rows(session: Session) -> None:
    account = _account(session)
    statement = _statement(session, sha_suffix="c")
    target = _transaction(session, account=account, statement=statement, description="Target")
    other = _transaction(session, account=account, statement=statement, description="Other")
    session.commit()
    categorizer = FakeCategorizer()

    updated = categorize_transactions(session, categorizer, transaction_ids=[target.id])
    session.commit()

    assert updated == 1
    session.expire_all()
    assert session.get(TransactionRow, target.id).category_id is not None  # type: ignore[union-attr]
    assert session.get(TransactionRow, other.id).category_id is None  # type: ignore[union-attr]


def test_examples_are_user_corrections_first_then_confident_ai(session: Session) -> None:
    account = _account(session)
    statement = _statement(session, sha_suffix="d")
    categories = _categories(session)
    grocery = next(c for c in categories if c.name == "Grocery")
    dining = next(c for c in categories if c.name == "Dining")
    now = datetime.now(timezone.utc)

    # A user correction for "Fictional Grocer" ...
    _transaction(
        session,
        account=account,
        statement=statement,
        description="Fictional Grocer",
        category_id=grocery.id,
        category_source="user",
        categorized_at=now,
    )
    # ... and a confident AI guess for "Fictional Diner".
    _transaction(
        session,
        account=account,
        statement=statement,
        description="Fictional Diner",
        category_id=dining.id,
        category_source="ai",
        category_confidence=Decimal("0.900"),
        categorized_at=now,
    )
    target = _transaction(session, account=account, statement=statement, description="Target")
    session.commit()

    captured: dict[str, Sequence[CategoryExample]] = {}

    def _decide(
        items: Sequence[CategorizeItem],
        cats: Sequence[CategoryOption],
        examples: Sequence[CategoryExample],
    ) -> list[CategoryDecision]:
        captured["examples"] = examples
        return [
            CategoryDecision(id=item.id, category_id=cats[0].id, confidence=Decimal("0.5"))
            for item in items
        ]

    categorizer = FakeCategorizer(decide=_decide)

    categorize_transactions(session, categorizer, transaction_ids=[target.id])
    session.commit()

    examples = captured["examples"]
    names = [e.category_name for e in examples]
    assert "Grocery" in names
    assert "Dining" in names
    assert names.index("Grocery") < names.index("Dining")


def test_low_confidence_ai_examples_are_excluded(session: Session) -> None:
    account = _account(session)
    statement = _statement(session, sha_suffix="e")
    categories = _categories(session)
    dining = next(c for c in categories if c.name == "Dining")
    now = datetime.now(timezone.utc)

    _transaction(
        session,
        account=account,
        statement=statement,
        description="Unsure Diner",
        category_id=dining.id,
        category_source="ai",
        category_confidence=Decimal("0.500"),
        categorized_at=now,
    )
    target = _transaction(session, account=account, statement=statement, description="Target")
    session.commit()

    captured: dict[str, Sequence[CategoryExample]] = {}

    def _decide(
        items: Sequence[CategorizeItem],
        cats: Sequence[CategoryOption],
        examples: Sequence[CategoryExample],
    ) -> list[CategoryDecision]:
        captured["examples"] = examples
        return [
            CategoryDecision(id=item.id, category_id=cats[0].id, confidence=Decimal("0.5"))
            for item in items
        ]

    categorizer = FakeCategorizer(decide=_decide)
    categorize_transactions(session, categorizer, transaction_ids=[target.id])
    session.commit()

    assert "Unsure Diner" not in [e.description for e in captured["examples"]]


def test_batching_splits_batches_over_one_hundred(session: Session) -> None:
    account = _account(session)
    statement = _statement(session, sha_suffix="f")
    for i in range(150):
        _transaction(session, account=account, statement=statement, description=f"Merchant {i}")
    session.commit()
    categorizer = FakeCategorizer()

    updated = categorize_transactions(session, categorizer, limit=150)
    session.commit()

    assert updated == 150
    assert len(categorizer.calls) == 2
    assert len(categorizer.calls[0]) == 100
    assert len(categorizer.calls[1]) == 50


def test_no_uncategorized_rows_returns_zero_without_calling_categorizer(session: Session) -> None:
    def _fail(
        items: Sequence[CategorizeItem],
        cats: Sequence[CategoryOption],
        examples: Sequence[CategoryExample],
    ) -> list[CategoryDecision]:
        raise AssertionError("should not be called with nothing to categorize")

    categorizer = FakeCategorizer(decide=_fail)

    updated = categorize_transactions(session, categorizer)

    assert updated == 0


def test_owner_correction_during_the_model_call_is_not_overwritten(session: Session) -> None:
    account = _account(session)
    statement = _statement(session, sha_suffix="race")
    row = _transaction(session, account=account, statement=statement)
    session.commit()
    categories = _categories(session)
    owner_choice, ai_choice = categories[0].id, categories[1].id

    def owner_edits_while_model_thinks(
        items: Sequence[CategorizeItem],
        options: Sequence[CategoryOption],
        examples: Sequence[CategoryExample],
    ) -> list[CategoryDecision]:
        # Simulates PATCH /transactions/{id} landing mid-call: the row was
        # loaded as uncategorized, but is user-categorized by write time.
        session.execute(
            update(TransactionRow)
            .where(TransactionRow.id == row.id)
            .values(category_id=owner_choice, category_source="user")
        )
        return [
            CategoryDecision(id=i.id, category_id=ai_choice, confidence=Decimal("0.99"))
            for i in items
        ]

    updated = categorize_transactions(
        session, FakeCategorizer(decide=owner_edits_while_model_thinks)
    )
    session.commit()

    assert updated == 0
    session.expire_all()
    refreshed = session.get(TransactionRow, row.id)
    assert refreshed is not None
    assert refreshed.category_id == owner_choice
    assert refreshed.category_source == "user"
