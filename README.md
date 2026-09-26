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
- [x] PostgreSQL schema & migrations
- [x] AI extraction (Claude) with totals reconciliation
- [ ] Categorization rules engine
- [x] Upload & query API

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
| `FINAGENT_CATEGORIZATION_MODEL` | Claude model used to categorize transactions | `claude-haiku-4-5` |
| `FINAGENT_CATEGORIZATION_REVIEW_THRESHOLD` | AI-categorized transactions below this confidence (0-1) are flagged `needs_review` | `0.7` |
| `FINAGENT_API_TOKEN` | Bearer token required by every endpoint except `GET /health` | none (fails closed) |
| `FINAGENT_RUN_WORKER` | Whether this process runs the background worker that drains the `POST /uploads` queue | `true` |

## API

Every endpoint except `GET /health` requires a bearer token, set via
`FINAGENT_API_TOKEN`:

```
Authorization: Bearer <FINAGENT_API_TOKEN>
```

| Method | Path | Description | Query / body params |
|--------|------|-------------|----------------------|
| `GET` | `/health` | Liveness check (no auth) | — |
| `GET` | `/api-info` | Server identity check for the browser UI (no auth) | — |
| `POST` | `/uploads` | Queue a statement file for background extraction; returns immediately (`202`). Re-uploading identical bytes is immediately `DONE` and never calls the extractor. Poll `GET /uploads/{id}` for the outcome. | body: `file` (multipart) |
| `GET` | `/uploads` | List uploads, newest first | `limit` (default 50, max 500), `offset` |
| `GET` | `/uploads/{upload_id}` | Fetch one upload's status | — |
| `POST` | `/statements` | Upload a statement file for *synchronous* extraction and persistence (for scripts; the browser UI uses `/uploads` instead, since extraction can take 30-90s and the tunnel in front of this API cuts requests off at ~100s). Re-uploading identical bytes is a no-op (`already_imported: true`) and never re-calls the extractor. | body: `file` (multipart) |
| `GET` | `/statements` | List statements, newest first | `status`, `limit` (default 50, max 500), `offset` |
| `GET` | `/statements/{statement_id}` | Fetch one statement | `include_extraction` (bool, default false) |
| `GET` | `/accounts` | List accounts | — |
| `GET` | `/transactions` | List transactions, newest first | `account_id`, `date_from`, `date_to`, `category_id`, `limit` (default 100, max 1000), `offset` |
| `POST` | `/transactions/confirm` | Mark listed, already-categorized transactions as owner-confirmed (`category_source='user'`); uncategorized or unknown ids are skipped | body: `ids` (1-500 transaction ids) |
| `GET` | `/categories` | List categories | — |

Queue a statement for background extraction with curl (recommended -- doesn't block on the 30-90s extraction):

```bash
curl -H "Authorization: Bearer $TOKEN" -F file=@statement.pdf http://localhost:8000/uploads
# {"id": 1, "status": "QUEUED", ...} -- poll:
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/uploads/1
```

Or upload synchronously (blocks until extraction finishes):

```bash
curl -H "Authorization: Bearer $TOKEN" -F file=@statement.pdf http://localhost:8000/statements
```

## Deploy (homeserver)

The API ships as a Docker image built from this repo's `Dockerfile`
(multi-stage build, non-root runtime user, `alembic upgrade head` run on
container start before `uvicorn` starts). To add it to the homeserver's
existing `crestlink-web` Portainer stack, see
[`deploy/portainer-service.yml`](deploy/portainer-service.yml) — it has the
service block to paste in plus step-by-step instructions in its header
comment.

## Development

See [AGENTS.md](AGENTS.md) for contributing standards, code layout, and architecture decisions.

### Local database

For local development and testing, use the bundled PostgreSQL via `pgserver`:

```bash
pip install -e ".[dev,localdb]"
python scripts/dev_db.py
```

This starts a local PostgreSQL server in `build/pgdata/` and prints two environment variable
assignments. To run pytest with the test database:

```powershell
# PowerShell
$env:FINAGENT_DATABASE_URL="postgresql+psycopg://postgres:@127.0.0.1:<port>/finagent_test"
pytest
```

```bash
# bash
export FINAGENT_DATABASE_URL="postgresql+psycopg://postgres:@127.0.0.1:<port>/finagent_test"
pytest
```

Use `python scripts/dev_db.py --stop` to stop the server (data persists).

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
