"""Pure orchestration for AI categorization (AGENTS.md: no business logic in routes).

``categorize_transactions`` loads uncategorized transactions, the category
list, and the owner's preference examples, sends them to the categorizer in
batches, and writes back ``category_id`` / ``category_source='ai'`` /
``category_confidence`` / ``categorized_at``. It never overwrites a row
whose ``category_source`` is already ``'user'``.
"""

from collections.abc import Sequence
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from finagent.categorize.base import (
    CategorizeItem,
    CategoryDecision,
    CategoryExample,
    CategoryOption,
    TransactionCategorizer,
)
from finagent.db.models import Category
from finagent.db.models import Transaction as TransactionRow

_BATCH_SIZE = 100
_EXAMPLE_LIMIT = 100
_AI_EXAMPLE_MIN_CONFIDENCE = Decimal("0.8")


def categorize_transactions(
    session: Session,
    categorizer: TransactionCategorizer,
    *,
    transaction_ids: Sequence[int] | None = None,
    limit: int = 200,
) -> int:
    """Categorize up to ``limit`` uncategorized transactions.

    ``transaction_ids``, when given, restricts the pool to those ids (rows
    already ``category_source='user'`` are still excluded). Returns the
    number of rows updated.
    """
    rows = _load_uncategorized(session, transaction_ids=transaction_ids, limit=limit)
    if not rows:
        return 0

    categories = list(session.execute(select(Category).order_by(Category.id)).scalars().all())
    options = [
        CategoryOption(id=category.id, name=category.name, description=category.description)
        for category in categories
    ]
    examples = _load_examples(session)

    updated = 0
    for batch in _chunks(rows, _BATCH_SIZE):
        items = [_to_item(row) for row in batch]
        decisions = categorizer.categorize(items, options, examples)
        batch_ids = {row.id for row in batch}
        now = datetime.now(timezone.utc)
        for decision in decisions:
            if decision.id not in batch_ids:
                continue
            updated += _apply_ai_decision(session, decision, now)
    return updated


def _apply_ai_decision(session: Session, decision: CategoryDecision, now: datetime) -> int:
    """Write one AI decision unless the row changed since it was loaded.

    The model call takes seconds; if the owner categorized the row in the
    meantime, their choice must win. So this is a conditional UPDATE
    re-checking the row is still uncategorized and not user-set, rather
    than a write to the stale ORM object loaded before the call.
    """
    result = session.execute(
        update(TransactionRow)
        .where(
            TransactionRow.id == decision.id,
            TransactionRow.category_id.is_(None),
            or_(
                TransactionRow.category_source.is_(None),
                TransactionRow.category_source != "user",
            ),
        )
        .values(
            category_id=decision.category_id,
            category_source="ai",
            category_confidence=decision.confidence,
            categorized_at=now,
        )
        .returning(TransactionRow.id)
        .execution_options(synchronize_session=False)
    )
    return len(result.scalars().all())


def _load_uncategorized(
    session: Session, *, transaction_ids: Sequence[int] | None, limit: int
) -> list[TransactionRow]:
    stmt = select(TransactionRow).where(TransactionRow.category_id.is_(None))
    if transaction_ids is not None:
        stmt = stmt.where(TransactionRow.id.in_(transaction_ids))
    # Defense in depth: a category_id IS NULL row should never already carry
    # category_source='user', but never overwrite one if it somehow does.
    stmt = stmt.where(
        (TransactionRow.category_source.is_(None)) | (TransactionRow.category_source != "user")
    )
    stmt = stmt.order_by(TransactionRow.id).limit(limit)
    return list(session.execute(stmt).scalars().all())


def _to_item(row: TransactionRow) -> CategorizeItem:
    # Sign convention (AGENTS.md §3): positive amount = money out. The
    # categorizer sees an unsigned amount plus an explicit direction,
    # matching the extraction schema's own OUT/IN convention.
    direction: Literal["OUT", "IN"] = "OUT" if row.amount >= 0 else "IN"
    return CategorizeItem(
        id=row.id,
        description=row.description,
        amount=abs(row.amount),
        direction=direction,
        posted_date=row.posted_date,
    )


def _load_examples(session: Session) -> list[CategoryExample]:
    # User-corrected examples first: they're the strongest signal of the
    # owner's actual preference and must outrank confident-but-unreviewed AI
    # guesses in the prompt (AGENTS.md: "examples ... take precedence").
    user_examples = _examples_by_source(session, source="user", min_confidence=None)
    ai_examples = _examples_by_source(
        session, source="ai", min_confidence=_AI_EXAMPLE_MIN_CONFIDENCE
    )
    return user_examples + ai_examples


def _examples_by_source(
    session: Session, *, source: str, min_confidence: Decimal | None
) -> list[CategoryExample]:
    """The latest categorization per distinct description, for one source, most recent first."""
    base = (
        select(
            TransactionRow.description,
            Category.name.label("category_name"),
            TransactionRow.categorized_at,
        )
        .join(Category, TransactionRow.category_id == Category.id)
        .where(TransactionRow.category_source == source)
    )
    if min_confidence is not None:
        base = base.where(TransactionRow.category_confidence >= min_confidence)
    # DISTINCT ON (Postgres-specific -- AGENTS.md: DB tests run against real
    # Postgres, never SQLite) keeps only the latest row per description.
    base = base.distinct(TransactionRow.description).order_by(
        TransactionRow.description, TransactionRow.categorized_at.desc()
    )
    deduped = base.subquery()
    stmt = (
        select(deduped.c.description, deduped.c.category_name)
        .order_by(deduped.c.categorized_at.desc())
        .limit(_EXAMPLE_LIMIT)
    )
    rows = session.execute(stmt).mappings().all()
    return [
        CategoryExample(description=row["description"], category_name=row["category_name"])
        for row in rows
    ]


def _chunks(rows: Sequence[TransactionRow], size: int) -> list[list[TransactionRow]]:
    return [list(rows[i : i + size]) for i in range(0, len(rows), size)]
