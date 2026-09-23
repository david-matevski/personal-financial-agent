"""Engine and session factory, built lazily from ``Settings.database_url``."""

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from finagent.core.config import get_settings


@lru_cache
def get_engine() -> Engine:
    """Return the process-wide engine, created on first use."""
    return create_engine(get_settings().database_url)


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    """Return the process-wide session factory, created on first use."""
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Yield a session, for use as ``with session_scope() as session: ...``.

    The caller owns commit/rollback; this only guarantees the session is
    closed afterwards.
    """
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()
