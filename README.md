# Personal Financial Agent

[![Quality gate](https://github.com/david-matevski/personal-financial-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/david-matevski/personal-financial-agent/actions/workflows/ci.yml)
![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)

A self-hosted backend that extracts transactions from credit card statements (Amex, CIBC, TD, and more) via PDF text extraction with OCR fallback. Automatically categorizes spending, stores results in PostgreSQL, and exposes a REST API for querying your financial data.

## Pipeline

```
Statement (PDF / image / CSV / XLS)
   └─> ingest     : detect issuer (Amex, CIBC, TD, ...) and pick a parser
   └─> extract    : text-layer PDF parse first, OCR fallback for scans
   └─> normalize  : canonical Transaction model (dates, signs, currency)
   └─> categorize : rule-based first, ML/LLM-assisted later
   └─> persist    : PostgreSQL, idempotent (hash-based dedup)
   └─> expose     : REST API (FastAPI)
```

**Status:** early development

## Supported issuers

| Issuer | Status |
|--------|--------|
| Amex | Planned |
| CIBC | Planned |
| TD | Planned |

## Roadmap

- [x] Domain model & dedup hashing
- [x] Health API
- [ ] PostgreSQL schema & migrations
- [ ] PDF text extraction + OCR fallback
- [ ] Issuer parsers (Amex, CIBC, TD)
- [ ] Categorization rules engine
- [ ] Upload & query API

## Requirements

- **Python 3.10+**
- **PostgreSQL 16**
- **Tesseract OCR** (optional, for scanned statements)

## Quick start

```bash
git clone https://github.com/david-matevski/personal-financial-agent.git
cd personal-financial-agent
python -m venv .venv
.venv/Scripts/activate   # Windows; use .venv/bin/activate on macOS/Linux
cp .env.example .env
# Edit .env with your database URL and other settings
pip install -e ".[dev,ocr]"
uvicorn finagent.api.app:app --reload
```

Then check the health endpoint:
```
GET http://localhost:8000/health
```

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `FINAGENT_DATABASE_URL` | PostgreSQL connection string | `postgresql+psycopg://finagent:finagent@localhost:5432/finagent` |
| `FINAGENT_LOG_LEVEL` | Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL) | `INFO` |

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
