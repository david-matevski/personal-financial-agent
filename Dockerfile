# syntax=docker/dockerfile:1

# --- builder: build a wheel from source -------------------------------------
FROM python:3.12-slim AS builder

WORKDIR /src

RUN pip install --no-cache-dir --upgrade pip build

COPY pyproject.toml README.md AGENTS.md ./
COPY src ./src

RUN python -m build --wheel --outdir /dist

# --- runtime: install the wheel only, no dev extras -------------------------
FROM python:3.12-slim AS runtime

RUN useradd --create-home --shell /usr/sbin/nologin app

WORKDIR /app

COPY --from=builder /dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm -rf /tmp/*.whl

COPY alembic.ini ./alembic.ini
COPY migrations ./migrations
COPY docker/entrypoint.sh ./docker/entrypoint.sh

# Git on Windows may drop the exec bit; don't rely on it.
RUN chmod 0755 /app/docker/entrypoint.sh && chown -R app:app /app
USER app

EXPOSE 8000

HEALTHCHECK CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status==200 else 1)"

ENTRYPOINT ["/app/docker/entrypoint.sh"]
