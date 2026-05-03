# =============================================================================
# Fulfillment Service — Dockerfile (Multi-stage)
# Build context: supplychainforge/
# =============================================================================
FROM python:3.11-slim AS builder
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*
ENV VIRTUAL_ENV=/opt/venv
ENV PATH=$VIRTUAL_ENV/bin:$PATH
RUN python -m venv $VIRTUAL_ENV
COPY services/fulfillment/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.11-slim AS runtime
WORKDIR /app
ENV VIRTUAL_ENV=/opt/venv
ENV PATH=$VIRTUAL_ENV/bin:$PATH
COPY --from=builder /opt/venv /opt/venv
COPY services/fulfillment/app/ ./app/
COPY services/fulfillment/alembic/ ./alembic/
COPY services/fulfillment/alembic.ini .
COPY shared/ /shared/
COPY services/fulfillment/entrypoint.sh ./entrypoint.sh
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser
ENV PYTHONPATH=/app:/
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
EXPOSE 8002
CMD ["bash", "entrypoint.sh"]
