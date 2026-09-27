#!/usr/bin/env python3
"""Start or reuse a local PostgreSQL server for development and testing.

Runs the PostgreSQL 16 binaries bundled with the ``pgserver`` package (extra
``localdb``) from ``build/pgdata`` -- no system install or Docker needed. It
creates two databases: ``finagent`` (for the app) and ``finagent_test`` (for
pytest, which drops and recreates its schema).

Usage:
  python scripts/dev_db.py           # start or reuse the server, print URLs
  python scripts/dev_db.py --stop    # stop the server (data persists)

The server always listens on 127.0.0.1:54329 (override with
FINAGENT_DEV_DB_PORT), so connection URLs stay the same across restarts.
pgserver's own start-up is not used: it picks a random port each time and
gives up after 10 seconds, which is shorter than crash recovery after an
unclean shutdown (e.g. the PC restarting while the server was running).
"""

import os
import subprocess
import sys
from pathlib import Path

try:
    import psycopg
    from pgserver._commands import POSTGRES_BIN_PATH
except ImportError:
    print(
        "Error: the local database tools are not installed.\n"
        'Install them with: pip install -e ".[dev,localdb]"',
        file=sys.stderr,
    )
    sys.exit(1)

APP_DB = "finagent"
TEST_DB = "finagent_test"
USER = "postgres"
HOST = "127.0.0.1"
PORT = int(os.environ.get("FINAGENT_DEV_DB_PORT", "54329"))
# Crash recovery after an unclean shutdown can take well over a minute.
START_TIMEOUT_SECONDS = 180

BUILD_DIR = (Path(__file__).parent.parent / "build").resolve()
PGDATA = BUILD_DIR / "pgdata"
# Outside the data directory: a log file inside it can be held open by one
# process while recovery tries to open it, failing with a sharing violation.
LOGFILE = BUILD_DIR / "pgdata.log"


def _bin(name: str) -> str:
    return str(Path(POSTGRES_BIN_PATH) / name)


def _pg_ctl(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_bin("pg_ctl"), "-D", str(PGDATA), *args], capture_output=True, text=True
    )


def running_port() -> int | None:
    """Port of the server running on PGDATA, or None if it isn't running."""
    if _pg_ctl("status").returncode != 0:
        return None
    # postmaster.pid line 4 is the port the running server listens on.
    lines = (PGDATA / "postmaster.pid").read_text().splitlines()
    return int(lines[3])


def initialize() -> None:
    """Create the data directory on first use."""
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [_bin("initdb"), "-D", str(PGDATA), "-U", USER, "--auth=trust", "-E", "UTF8"],
        check=True,
        capture_output=True,
    )


def start() -> None:
    # Output is not captured: the postmaster pg_ctl launches inherits any
    # pipes we open and keeps them open, so capturing would block forever
    # (on Windows). Everything useful goes to LOGFILE anyway.
    result = subprocess.run(
        [
            _bin("pg_ctl"),
            "-D",
            str(PGDATA),
            "-l",
            str(LOGFILE),
            "-o",
            f"-h {HOST} -p {PORT}",
            "-w",
            "-t",
            str(START_TIMEOUT_SECONDS),
            "start",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        tail = LOGFILE.read_text(errors="replace").splitlines()[-15:] if LOGFILE.exists() else []
        print("\n".join(tail), file=sys.stderr)
        print(f"PostgreSQL did not start; full log: {LOGFILE}", file=sys.stderr)
        sys.exit(1)


def url(port: int, database: str, *, driver: str = "postgresql") -> str:
    return f"{driver}://{USER}:@{HOST}:{port}/{database}"


def ensure_databases(port: int) -> None:
    """Create the app and test databases if they don't exist yet."""
    with psycopg.connect(url(port, "postgres"), autocommit=True) as conn:
        for name in (APP_DB, TEST_DB):
            exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
            if exists.fetchone() is None:
                # Identifiers can't be parameters; names are fixed constants here.
                conn.execute(f'CREATE DATABASE "{name}"')


def main() -> int:
    if sys.argv[1:] == ["--stop"]:
        if running_port() is None:
            print("PostgreSQL is not running.")
            return 0
        _pg_ctl("-m", "fast", "-w", "stop")
        print(f"PostgreSQL stopped (data in {PGDATA} persists).")
        return 0

    if not (PGDATA / "PG_VERSION").exists():
        initialize()

    port = running_port()
    if port is None:
        start()
        port = PORT
    elif port != PORT:
        print(
            f"Note: server already running on port {port}; "
            f"it will use {PORT} after `--stop` and a fresh start.",
            file=sys.stderr,
        )

    ensure_databases(port)
    driver = "postgresql+psycopg"
    print(f"FINAGENT_DATABASE_URL={url(port, APP_DB, driver=driver)}")
    print(f"FINAGENT_DATABASE_URL={url(port, TEST_DB, driver=driver)}  # for pytest")
    return 0


if __name__ == "__main__":
    sys.exit(main())
