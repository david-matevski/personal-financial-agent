#!/usr/bin/env python3
"""
Start or reuse a local PostgreSQL server for development and testing.

This script manages a local PostgreSQL instance in the build/pgdata directory.
It creates two databases: finagent (for the app) and finagent_test (for pytest).

Usage:
  python scripts/dev_db.py           # Start/reuse server and print connection strings
  python scripts/dev_db.py --stop    # Stop the server (data persists)

Prints two environment variable lines ready to use:
  FINAGENT_DATABASE_URL=postgresql+psycopg://...finagent
  FINAGENT_DATABASE_URL=postgresql+psycopg://...finagent_test (for pytest)
"""

import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

# Check pgserver is installed
try:
    import pgserver
except ImportError:
    print(
        "Error: pgserver is not installed.\nInstall it with: pip install -e .[localdb]",
        file=sys.stderr,
    )
    sys.exit(1)

try:
    import psycopg
except ImportError:
    print(
        "Error: psycopg is not installed.\nInstall it with: pip install -e .",
        file=sys.stderr,
    )
    sys.exit(1)


APP_DB = "finagent"
TEST_DB = "finagent_test"
SQLALCHEMY_DRIVER = "postgresql+psycopg"


def get_pgdata_path() -> Path:
    """Get the absolute path to the pgdata directory."""
    repo_root = Path(__file__).parent.parent
    pgdata = repo_root / "build" / "pgdata"
    return pgdata.resolve()


def with_database(uri: str, database: str, *, driver: str = "postgresql") -> str:
    """Return ``uri`` pointing at ``database``, keeping user, host and port."""
    parts = urlsplit(uri)
    return urlunsplit((driver, parts.netloc, f"/{database}", parts.query, ""))


def ensure_databases(uri: str, names: tuple[str, ...]) -> None:
    """Create each database in ``names`` that doesn't exist yet."""
    with psycopg.connect(with_database(uri, "postgres"), autocommit=True) as conn:
        for name in names:
            exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
            if exists.fetchone() is None:
                # Identifiers can't be parameters; names are fixed constants here.
                conn.execute(f'CREATE DATABASE "{name}"')


def main() -> int:
    """Main entry point."""
    pgdata = get_pgdata_path()

    # Handle --stop flag
    if len(sys.argv) > 1 and sys.argv[1] == "--stop":
        try:
            server = pgserver.get_server(str(pgdata), cleanup_mode=None)
            server.stop()
            print(f"PostgreSQL server stopped (data in {pgdata} persists)")
            return 0
        except Exception as e:
            print(f"Error stopping server: {e}", file=sys.stderr)
            return 1

    # Start or reuse the server
    try:
        pgdata.parent.mkdir(parents=True, exist_ok=True)
        server = pgserver.get_server(str(pgdata), cleanup_mode=None)
        db_url = server.get_uri()
    except Exception as e:
        print(f"Error starting PostgreSQL server: {e}", file=sys.stderr)
        return 1

    ensure_databases(db_url, (APP_DB, TEST_DB))

    print(f"FINAGENT_DATABASE_URL={with_database(db_url, APP_DB, driver=SQLALCHEMY_DRIVER)}")
    print(
        f"FINAGENT_DATABASE_URL={with_database(db_url, TEST_DB, driver=SQLALCHEMY_DRIVER)}"
        "  # for pytest"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
