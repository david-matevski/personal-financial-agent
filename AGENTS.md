# AGENTS.md

Operating rules for every AI agent (and human) contributing to this repo.
Read this in full before making changes. If a rule here conflicts with a
one-off instruction in a task prompt, the task prompt wins for that task only.

---

## 1. What this project is

A self-hosted personal-finance backend:

```
Statement (PDF / image / CSV / XLS)
   └─> ingest     : detect issuer (Amex, CIBC, TD, ...) and pick a parser
   └─> extract    : text-layer PDF parse first, OCR fallback for scans
   └─> normalize  : canonical Transaction model (dates, signs, currency)
   └─> categorize : rule-based first, ML/LLM-assisted later
   └─> persist    : PostgreSQL, idempotent (hash-based dedup)
   └─> expose     : REST API (FastAPI)
```

**This is a PUBLIC repository.** Real financial data never enters git. See §6.

---

## 2. Agent roles and model tiering

Work is split so the most capable model spends its effort on judgement, and
cheaper models do the bulk of the typing.

| Role | Model | Owns | Must not |
|---|---|---|---|
| **Orchestrator** | Opus | Architecture, task breakdown, schema/API design decisions, reviewing every diff before commit, editing this file | Write large amounts of feature code itself when a delegate could |
| **Implementer** (`.claude/agents/implementer.md`) | Sonnet | Feature code, parsers, migrations, API endpoints, the tests for them | Change architecture, public API contracts, or DB schema beyond the task spec without flagging it |
| **Chore** (`.claude/agents/chore.md`) | Haiku | Docs, fixtures, renames, formatting, dependency bumps, boilerplate, small well-specified edits | Make design decisions; touch more files than the task lists |
| **Reviewer** (`.claude/agents/reviewer.md`) | Sonnet | Read-only review of a diff against this file; reports findings | Edit files |

### Orchestration loop

1. Orchestrator writes a **task spec**: goal, files in scope, interfaces to
   honour, acceptance criteria (tests that must pass), out-of-scope list.
2. Delegate implements on the spec, runs the quality gate (§4), and reports
   back: files changed, test results, anything it was unsure about.
3. Orchestrator (or Reviewer for larger diffs) reviews. Rework goes back to
   the same delegate with specific feedback.
4. Orchestrator makes the commit(s) per §5.

Delegates do not commit unless the task spec explicitly says to.
Independent tasks run in parallel; tasks touching the same files do not.

---

## 3. Code standards

**Stack:** Python ≥ 3.10 · FastAPI · SQLAlchemy 2.x (typed, `Mapped[]`) ·
Alembic · Pydantic v2 · PostgreSQL 16 · pytest · ruff · mypy (strict).

### Layout

```
src/finagent/
  api/            FastAPI routers + request/response schemas only. No business logic.
  core/           config (pydantic-settings), logging, shared types
  domain/         pure models & logic (Transaction, Money, hashing). No I/O.
  ingest/
    extract/      PDF text / OCR backends behind one Protocol
    parsers/      one module per issuer: amex.py, cibc.py, td.py ...
  categorize/     rule engine, later ML
  db/             SQLAlchemy models, session, repositories
migrations/       Alembic
tests/            mirrors src/ layout; fixtures/ holds SYNTHETIC samples only
```

### Rules

- **Money is `Decimal`, never `float`.** Store as `NUMERIC(14,2)`.
- **Sign convention:** positive = money out (purchases, fees); negative =
  money in (payments, refunds, income). Normalise in the parser, nowhere else.
- **Dates** are `datetime.date`, America/Toronto assumed unless the source says otherwise.
- **Dedup:** every transaction gets a deterministic SHA-256 `transaction_hash`;
  inserts are `ON CONFLICT DO NOTHING`. Re-importing a statement is a no-op.
- **One parser per issuer format**, each implementing the `StatementParser`
  protocol (`can_parse(doc) -> bool`, `parse(doc) -> ParsedStatement`) over a
  `SourceDocument` (`ingest/document.py`): PDFs arrive as page text, exports
  (XLS/XLSX/CSV) as rows. Adding an issuer must not require editing another
  issuer's parser.
- **Parsers reconcile.** Where a statement prints totals (previous/new
  balance, charges, payments), the parser checks its transactions sum to
  them and raises `ParseError` on mismatch. Never return partial data.
- **Extraction strategy:** text-layer first (pdfplumber); OCR only when the
  page has no usable text. OCR backend is swappable behind a Protocol.
- Type hints everywhere; `mypy --strict` clean. No `Any` without a comment saying why.
- Functions do one thing. Prefer pure functions in `domain/`; push I/O to the edges.
- No dead code, commented-out code, or speculative abstractions. Build what
  the current task needs.
- Comments explain *why*, not *what*. Docstrings on public functions/classes.
- Errors: raise specific exceptions from `core/errors.py`; the API layer maps
  them to HTTP responses. Never swallow exceptions silently.
- Logging via the stdlib `logging` module. **Never log raw statement text,
  card numbers, or amounts tied to a merchant at INFO or above.**
- Config only via environment variables (`core/config.py`). No hard-coded
  hosts, credentials, or paths.

### Tests

- Every parser ships with tests against **synthetic** fixtures that mimic the
  issuer's layout (fake names, fake card numbers, made-up merchants).
- Domain logic: unit tests. API: `httpx` / FastAPI `TestClient` tests.
- DB tests run against a real Postgres (docker compose / CI service), not SQLite.
- A bug fix includes a test that fails without the fix.

---

## 4. Quality gate (run before reporting a task done)

```bash
ruff format .
ruff check .
mypy src
pytest
```

All four must pass. If something can't pass (e.g. no Postgres locally),
say so explicitly in the report — never claim green when it isn't.

---

## 5. Commits

[Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <imperative summary, ≤ 72 chars, no trailing period>

<body: what and why, wrapped at 72. Optional for trivial changes.>
```

- **types:** `feat` `fix` `refactor` `test` `docs` `chore` `build` `ci` `perf`
- **scopes:** `api` `ingest` `parser/<issuer>` `ocr` `categorize` `db` `core` `deps` `repo`
- One logical change per commit. Tests go in the same commit as the code
  they test. Formatting-only changes go in their own commit.
- Every commit passes the quality gate (§4) on its own.
- Never commit secrets, `.env`, statements, or real transaction data.
- Work on a branch (`feat/...`, `fix/...`); `main` stays releasable.
- No `--no-verify`, no force-push to `main`.

Examples:
```
feat(parser/amex): parse Amex Gold PDF statement transactions
fix(ingest): treat CR suffix as a credit on CIBC statements
test(categorize): cover priority ordering of overlapping rules
```

---

## 6. Data safety (public repo)

- `data/`, `statements/`, `*.pdf`, `*.xls*`, `*.csv` are git-ignored
  everywhere except `tests/fixtures/`, which holds **synthetic** files only.
- Before adding a fixture, confirm it contains no real names, addresses,
  account/card numbers (even partial), or real transactions.
- `.env` is ignored; `.env.example` documents every variable with dummy values.
- If you ever see real personal data staged, stop and report it. Do not commit.
- Real sample statements live in the git-ignored `statements/` folder so
  parsers can be developed against true layouts. Agents may **read** them
  to learn structure, but must never copy their contents into code,
  comments, tests, fixtures, commit messages, or task reports: no real
  merchant lines, names, addresses, amounts, card/account digits. Fixtures
  are written from scratch with invented values that mimic the layout.
- Parser code matches on layout markers (headings, column labels, date/amount
  patterns) — never on the account holder's name or account numbers.

---

## 7. When unsure

Delegates: stop and report the question rather than guessing on anything
that changes a public interface, the DB schema, or the data-safety rules.
Small local choices (naming a private helper, ordering of tests) — just decide.
