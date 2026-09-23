# Personal Financial Agent

[![Quality gate](https://github.com/david-matevski/personal-financial-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/david-matevski/personal-financial-agent/actions/workflows/ci.yml)
![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)

A self-hosted backend that extracts transactions from any bank or credit card statement (PDF, image, CSV, or Excel export) using Claude, verifies them against the statement's own totals, categorizes spending, stores results in PostgreSQL, and exposes a REST API for querying your financial data.

## Pipeline

```
Statement (PDF / image / CSV / XLS)
   └─> ingest     : detect format and load into SourceDocument
   └─> extract    : Claude reads document and transcribes to structured JSON
   └─> validate   : transactions must reconcile to the printed totals
   └─> normalize  : canonical Transaction model (dates, signs, currency)
   └─> categorize : rule-based first, ML/LLM-assisted later
   └─> persist    : PostgreSQL, idempotent (hash-based dedup)
   └─> expose     : REST API (FastAPI)
```

**Status:** early development

## Supported statements

There are no per-bank parsers: any statement Claude can read is supported,
and every extraction is checked against the statement's printed totals.

| Verified so far | Format |
|--------|--------|
| Amex | XLS transaction export |
| TD Visa | PDF statement |

## Roadmap

- [x] Domain model & dedup hashing
- [x] Health API
- [ ] PostgreSQL schema & migrations
- [x] AI extraction (Claude) with totals reconciliation
- [ ] Categorization rules engine
- [ ] Upload & query API

## Requirements

- **Python 3.10+**
- **PostgreSQL 16**

## Quick start

```bash
git clone https://github.com/david-matevski/personal-financial-agent.git
cd personal-financial-agent
python -m venv .venv
.venv/Scripts/activate   # Windows; use .venv/bin/activate on macOS/Linux
cp .env.example .env
# Edit .env with your database URL and other settings
pip install -e ".[dev]"
uvicorn finagent.api.app:app --reload
```

Then check the health endpoint:
```
GET http://localhost:8000/health
```

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `ANTHROPIC_API_KEY` | Anthropic API key for statement extraction | none |
| `FINAGENT_DATABASE_URL` | PostgreSQL connection string | `postgresql+psycopg://finagent:finagent@localhost:5432/finagent` |
| `FINAGENT_LOG_LEVEL` | Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL) | `INFO` |
| `FINAGENT_EXTRACTION_MODEL` | Claude model used to extract transactions from statements | `claude-opus-5-5` |
| `FINAGENT_EXTRACTION_EFFORT` | Claude reasoning effort (low, medium, high, xhigh, max) | `high` |

## Development

See [AGENTS.md](AGENTS.md) for contributing standards, code layout, and architecture decisions.

Quality gate — all four must pass:
```bash
ruff format .
ruff check .
mypy src
pytest
```

## Contributing

PRs are welcome. Please follow [Conventional Commits](https://www.conventionalcommits.org/) and ensure the quality gate passes before opening a PR. See [AGENTS.md](AGENTS.md) for detailed standards.

## Privacy

**Never commit real financial data.** This repository is public. Keep your real statements in the git-ignored `statements/` folder. The `.gitignore` also excludes statement PDFs, spreadsheets, scans/photos, database dumps, archives, and logs everywhere except `tests/fixtures/`, which contains only synthetic test fixtures with fake names, accounts, and transactions. Before adding any fixture, confirm it contains no real names, addresses, account/card numbers, or actual transactions.

## License

MIT — see [LICENSE](LICENSE)
