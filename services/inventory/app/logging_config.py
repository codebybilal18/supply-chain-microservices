"""
Structured JSON logging configuration.

Why structured logging?
  - Cloud Logging (GCP) ingests JSON logs and indexes each field.
  - Structured logs let you filter by service, level, trace_id, etc.
  - Compatible with local development (human-readable via jq or raw).

The format matches the Google Cloud Logging JSON payload convention so
that Cloud Run picks up severity correctly without extra configuration.
"""

import logging
import sys

from app.config import settings


class JSONFormatter(logging.Formatter):
    """Emit log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        import json
        import traceback

        payload: dict = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "service": settings.SERVICE_NAME,
            "version": settings.SERVICE_VERSION,
            "module": record.module,
            "funcName": record.funcName,
            "lineno": record.lineno,
        }

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


def setup_logging() -> None:
    """Configure root logger. Call once at application startup."""
    log_level = logging.DEBUG if settings.DEBUG else logging.INFO

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers.clear()
    root_logger.addHandler(handler)

    # Silence noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.DEBUG if settings.DEBUG else logging.WARNING
    )
