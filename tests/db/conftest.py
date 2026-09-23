"""Shared fixtures for tests/db.

These tests run against a real Postgres (AGENTS.md: "DB tests run against a
real Postgres ... not SQLite"). If ``FINAGENT_DATABASE_URL`` is unreachable
(no local Postgres, no Docker), the whole module is skipped -- CI provides
Postgres 16, so they run there.
"""

import os
from collections.abc import Iterator

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_ALEMBIC_INI = os.path.join(_REPO_ROOT, "alembic.ini")

_DEFAULT_URL = "postgresql+psycopg://finagent:finagent@localhost:5432/finagent"


def _database_url() -> str:
    return os.environ.get("FINAGENT_DATABASE_URL", _DEFAULT_URL)


def _psycopg_dsn(sqlalchemy_url: str) -> str:
    # psycopg.connect doesn't understand the "postgresql+psycopg://" driver
    # suffix SQLAlchemy uses; strip it down to a plain "postgresql://" DSN.
    return sqlalchemy_url.replace("postgresql+psycopg://", "postgresql://", 1)


def _is_reachable(url: str) -> bool:
    try:
        with psycopg.connect(_psycopg_dsn(url), connect_timeout=2) as conn:
            conn.close()
        return True
    except OSError:
        return False
    except psycopg.OperationalError:
        return False


@pytest.fixture(scope="session")
def db_engine() -> Iterator[Engine]:
    """A fresh, migrated Postgres schema for the whole test session.

    Drops and recreates the ``public`` schema so the suite is re-runnable
    against a persistent local Postgres, then applies every migration.
    """
    url = _database_url()
    if not _is_reachable(url):
        pytest.skip(f"Postgres not reachable at {url!r}; skipping tests/db")

    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))

    alembic_cfg = Config(_ALEMBIC_INI)
    alembic_cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(alembic_cfg, "head")

    yield engine

    engine.dispose()


@pytest.fixture
def session(db_engine: Engine) -> Iterator[Session]:
    """A session bound to the migrated schema, cleaned of non-seed data after each test."""
    factory = sessionmaker(bind=db_engine, expire_on_commit=False)
    with factory() as session:
        yield session
        session.rollback()
        session.execute(
            text("TRUNCATE transactions, statements, accounts RESTART IDENTITY CASCADE")
        )
        session.commit()
