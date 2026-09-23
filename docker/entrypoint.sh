#!/usr/bin/env bash
set -euo pipefail

cd /app

alembic upgrade head

exec uvicorn finagent.api.app:app --host 0.0.0.0 --port 8000 --proxy-headers
