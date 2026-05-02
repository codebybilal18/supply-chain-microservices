#!/usr/bin/env bash
# =============================================================================
# Order Service — Container Entrypoint
# Runs Alembic migrations, then starts the uvicorn server.
# =============================================================================
set -euo pipefail

echo "[entrypoint] Running Alembic migrations for order service..."
alembic upgrade head
echo "[entrypoint] Migrations complete."

exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --workers 1 \
  --loop uvloop \
  --http httptools
