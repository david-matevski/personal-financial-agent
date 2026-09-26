"""Pure orchestration for AI categorization (AGENTS.md: no business logic in routes).

``categorize_transactions`` loads the categorization pool, the category
list, and the owner's preference examples, sends them to the categorizer in
batches, and writes back ``category_id`` / ``category_source='ai'`` /
``category_confidence`` / ``categorized_at``. It never overwrites a row
whose ``category_source`` is already ``'user'``.

The pool is either just-uncategorized rows (the default), or, with
``include_ai=True``, every row that isn't user-set -- so a category-list
change (e.g. adding Golf) can be reflected in transactions the AI already
filed elsewhere. ``load_pool``/``count_pool`` are exposed for callers (the
API route) that need to page through the include_ai pool with a cursor.
"""

from collections.abc import Sequence
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from sqlalchemy import ColumnElement, func, or_, select, update
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
    include_ai: bool = False,
    after_id: int | None = None,
) -> int:
    """Categorize up to ``limit`` rows from the pool.

    ``transaction_ids``, when given, restricts the pool to those ids (rows
    already ``category_source='user'`` are still excluded). With
    ``include_ai=True`` the pool also includes rows previously categorized
    by AI, letting them be re-run after the category list changes; user
    rows are never touched either way. ``after_id`` restricts the pool to
    ids greater than it, for paging. Returns the number of rows updated.
    """
    rows = load_pool(
        session,
        transaction_ids=transaction_ids,
        limit=limit,
        include_ai=include_ai,
        after_id=after_id,
    )
    if not rows:
        return 0

    categories = list(session.execute(select(Category).order_by(Category.id)).scalars().all())
    options = [
        CategoryOption(id=category.id, name=category.name, description=category.description)
        for category in categories
    ]
    # Exclude the rows being (re-)categorized from the AI example set: a row
    # that's part of this pool must not prime the model with its own
    # previous (possibly wrong) answer.
    examples = _load_examples(session, exclude_ids={row.id for row in rows})

    updated = 0
    for batch in _chunks(rows, _BATCH_SIZE):
        items = [_to_item(row) for row in batch]
        decisions = categorizer.categorize(items, options, examples)
        batch_ids = {row.id for row in batch}
        now = datetime.now(timezone.utc)
        for decision in decisions:
            if decision.id not in batch_ids:
                continue
            updated += _apply_ai_decision(session, decision, now, include_ai=include_ai)
    return updated


def _apply_ai_decision(
    session: Session, decision: CategoryDecision, now: datetime, *, include_ai: bool
) -> int:
    """Write one AI decision unless the row left the pool since it was loaded.

    The model call takes seconds; if the owner categorized the row in the
    meantime, their choice must win. So this is a conditional UPDATE
    re-checking the exact pool condition at write time, rather than a write
    to the stale ORM object loaded before the call: the row must not be
    user-set, and (outside include_ai) must still be uncategorized.
    """
    conditions: list[ColumnElement[bool]] = [
        TransactionRow.id == decision.id,
        *_pool_conditions(include_ai=include_ai),
    ]
    result = session.execute(
        update(TransactionRow)
        .where(*conditions)
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


def _pool_conditions(*, include_ai: bool) -> list[ColumnElement[bool]]:
    """The categorization pool: never user-set, and uncategorized unless include_ai."""
    conditions: list[ColumnElement[bool]] = [
        or_(
            TransactionRow.category_source.is_(None),
            TransactionRow.category_source != "user",
        )
    ]
    if not include_ai:
        conditions.append(TransactionRow.category_id.is_(None))
    return conditions


def load_pool(
    session: Session,
    *,
    transaction_ids: Sequence[int] | None = None,
    limit: int,
    include_ai: bool = False,
    after_id: int | None = None,
) -> list[TransactionRow]:
    """The rows ``categorize_transactions`` would pick up next, ascending by id.

    Exposed so the API route can page through the ``include_ai`` pool with
    a cursor (``after_id``) and report back a stable ``last_id``.
    """
    stmt = select(TransactionRow).where(*_pool_conditions(include_ai=include_ai))
    if transaction_ids is not None:
        stmt = stmt.where(TransactionRow.id.in_(transaction_ids))
    if after_id is not None:
        stmt = stmt.where(TransactionRow.id > after_id)
    stmt = stmt.order_by(TransactionRow.id).limit(limit)
    return list(session.execute(stmt).scalars().all())


def count_pool(session: Session, *, include_ai: bool = False, after_id: int | None = None) -> int:
    """How many rows remain in the pool (optionally after a cursor)."""
    stmt = (
        select(func.count())
        .select_from(TransactionRow)
        .where(*_pool_conditions(include_ai=include_ai))
    )
    if after_id is not None:
        stmt = stmt.where(TransactionRow.id > after_id)
    return session.execute(stmt).scalar_one()


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


def _load_examples(
    session: Session, *, exclude_ids: set[int] | None = None
) -> list[CategoryExample]:
    # User-corrected examples first: they're the strongest signal of the
    # owner's actual preference and must outrank confident-but-unreviewed AI
    # guesses in the prompt (AGENTS.md: "examples ... take precedence").
    user_examples = _examples_by_source(session, source="user", min_confidence=None)
    # AI examples exclude the rows being (re-)categorized in this call: an
    # include_ai run must not prime the model with its own previous answer
    # for the very rows it's being asked to reconsider.
    ai_examples = _examples_by_source(
        session,
        source="ai",
        min_confidence=_AI_EXAMPLE_MIN_CONFIDENCE,
        exclude_ids=exclude_ids,
    )
    return user_examples + ai_examples


def _examples_by_source(
    session: Session,
    *,
    source: str,
    min_confidence: Decimal | None,
    exclude_ids: set[int] | None = None,
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
    if exclude_ids:
        base = base.where(TransactionRow.id.notin_(exclude_ids))
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
