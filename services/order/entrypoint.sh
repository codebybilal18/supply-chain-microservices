#!/usr/bin/env bash
# =============================================================================
# Order Service — Container Entrypoint
# Runs Alembic migrations, then starts the uvicorn server.
# =============================================================================
set -euo pipefail

# Wait for the Cloud SQL Auth Proxy sidecar to accept connections on 127.0.0.1:3306.
echo "[entrypoint] Waiting for Cloud SQL proxy on 127.0.0.1:3306..."
MAX_WAIT=60
ELAPSED=0
until python -c "import socket; s=socket.socket(); s.settimeout(1); s.connect(('127.0.0.1', 3306)); s.close()" 2>/dev/null; do
  if [ "$ELAPSED" -ge "$MAX_WAIT" ]; then
    echo "[entrypoint] Timed out waiting for Cloud SQL proxy after ${MAX_WAIT}s." >&2
    exit 1
  fi
  sleep 2
  ELAPSED=$((ELAPSED + 2))
done
echo "[entrypoint] Cloud SQL proxy ready (${ELAPSED}s)."

echo "[entrypoint] Running Alembic migrations for order service..."
alembic upgrade head
echo "[entrypoint] Migrations complete."

exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --workers 1 \
  --loop uvloop \
  --http httptools
