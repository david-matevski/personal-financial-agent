"""Migration round-trip test: downgrade to base, then upgrade back to head."""

import os

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, inspect

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_ALEMBIC_INI = os.path.join(_REPO_ROOT, "alembic.ini")


def _config(url: str) -> Config:
    cfg = Config(_ALEMBIC_INI)
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def test_downgrade_then_upgrade_roundtrip(db_engine: Engine) -> None:
    url = db_engine.url.render_as_string(hide_password=False)
    cfg = _config(url)

    command.downgrade(cfg, "base")
    inspector = inspect(db_engine)
    assert "accounts" not in inspector.get_table_names()
    assert "transactions" not in inspector.get_table_names()

    command.upgrade(cfg, "head")
    inspector = inspect(db_engine)
    tables = set(inspector.get_table_names())
    assert {"accounts", "statements", "categories", "transactions"} <= tables
    assert "category_rules" not in tables

    with db_engine.connect() as conn:
        (count,) = conn.exec_driver_sql("SELECT count(*) FROM categories").fetchone()
        assert count == 15
        (described,) = conn.exec_driver_sql(
            "SELECT count(*) FROM categories WHERE description IS NOT NULL"
        ).fetchone()
        assert described == 15
