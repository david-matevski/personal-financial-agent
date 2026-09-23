"""Evaluate real-statement extraction accuracy against hand-built baselines.

**Costs money and sends real statements to Anthropic.** Run manually only
(never in CI): for every file in the git-ignored ``statements/`` directory
that has a matching ``statements/expected/<name>.json`` baseline, this runs
the real ``extract_statement`` pipeline against the live Anthropic API and
reports how well it did.

Usage:

    .venv/Scripts/python scripts/eval_extraction.py

Settings (including ``ANTHROPIC_API_KEY``) are loaded from ``.env`` via
``finagent.core.config.get_settings``. Output never includes descriptions
or amounts (AGENTS.md §6: real statement contents must never be copied out
of the git-ignored ``statements/`` folder), only counts.
"""

import json
import sys
from collections import Counter
from pathlib import Path

from finagent.core.config import build_extractor, get_settings
from finagent.core.errors import FinAgentError
from finagent.ingest.extract.base import StatementExtractor
from finagent.ingest.pipeline import extract_statement

STATEMENTS_DIR = Path(__file__).parent.parent / "statements"
EXPECTED_DIR = STATEMENTS_DIR / "expected"


def _expected_path_for(statement_path: Path) -> Path:
    return EXPECTED_DIR / f"{statement_path.name}.json"


def main() -> int:
    if not STATEMENTS_DIR.is_dir():
        print(f"No statements/ directory found at {STATEMENTS_DIR}", file=sys.stderr)
        return 1

    settings = get_settings()
    try:
        extractor = build_extractor(settings)
    except FinAgentError as exc:
        print(f"Cannot build extractor: {exc}", file=sys.stderr)
        return 1

    statement_paths = sorted(p for p in STATEMENTS_DIR.iterdir() if p.is_file())
    evaluated = 0
    for statement_path in statement_paths:
        expected_path = _expected_path_for(statement_path)
        if not expected_path.is_file():
            continue
        evaluated += 1
        _evaluate_one(statement_path, expected_path, extractor)

    if evaluated == 0:
        print("No statements had a matching statements/expected/<name>.json baseline.")
    return 0


def _evaluate_one(statement_path: Path, expected_path: Path, extractor: StatementExtractor) -> None:
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    # Counters, not sets: identical same-day charges are legitimate and must
    # each be extracted, so duplicates have to count individually.
    expected_keys = Counter(
        (tx["posted_date"], tx["amount"]) for tx in expected.get("transactions", [])
    )

    try:
        data = statement_path.read_bytes()
        result = extract_statement(statement_path.name, data, extractor)
    except FinAgentError as exc:
        print(f"{statement_path.name}: ERROR ({type(exc).__name__})")
        return

    actual_keys = Counter(
        (tx.posted_date.isoformat(), f"{tx.amount:.2f}") for tx in result.statement.transactions
    )
    matches = expected_keys & actual_keys
    missing = expected_keys - actual_keys
    extra = actual_keys - expected_keys

    print(
        f"{statement_path.name}: status={result.status.value} attempts={result.attempts} "
        f"extracted={actual_keys.total()} expected={expected_keys.total()} "
        f"matches={matches.total()} missing={missing.total()} extra={extra.total()}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
