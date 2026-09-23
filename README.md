# Personal Financial Agent

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

## Quick start

```bash
python -m venv .venv
.venv/Scripts/activate   # Windows; use .venv/bin/activate on macOS/Linux
pip install -e ".[dev,ocr]"
uvicorn finagent.api.app:app --reload
```

Then check the health endpoint:
```
GET http://localhost:8000/health
```

**Note:** OCR fallback requires the Tesseract binary installed on your system. See [tesseract-ocr](https://github.com/UB-Mannheim/tesseract/wiki) for installation instructions.

## Development

See [AGENTS.md](AGENTS.md) for contributing standards, code layout, and architecture decisions.

Quality gate — all four must pass:
```bash
ruff format .
ruff check .
mypy src
pytest
```

## Privacy

**Never commit real financial data.** This repository is public. The `.gitignore` excludes statement PDFs, CSVs, and other raw files everywhere except `tests/fixtures/`, which contains only synthetic test fixtures with fake names, accounts, and transactions. Before adding any fixture, confirm it contains no real names, addresses, account/card numbers, or actual transactions.

## License

MIT — see [LICENSE](LICENSE)
