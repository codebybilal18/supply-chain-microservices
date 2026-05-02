# =============================================================================
# Inventory Service — Dockerfile (Multi-stage build)
# =============================================================================
# Stage 1  builder  — installs Python dependencies into /root/.local
# Stage 2  runtime  — lean production image, non-root user, no build tools
#
# Build:  docker build --target runtime -t scf-inventory:latest .
# Run:    docker run -p 8000:8000 --env-file .env scf-inventory:latest
# =============================================================================

# ── Stage 1: Builder ──────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# Install gcc for packages that compile C extensions (aiomysql, etc.)
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# ── Stage 2: Runtime ──────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

# Copy only the installed packages from builder — no build tools in runtime
COPY --from=builder /root/.local /root/.local

# Copy application source
COPY app/ ./app/

# Security: run as non-root
RUN useradd -m -u 1000 appuser \
    && chown -R appuser:appuser /app
USER appuser

# Ensure user-installed packages are on PATH
ENV PATH=/root/.local/bin:$PATH
ENV PYTHONPATH=/app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

# Graceful shutdown: uvicorn respects SIGTERM
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--loop", "uvloop", "--http", "httptools"]
