"""
Request ID middleware.

Attaches a unique X-Request-ID to every inbound request and echoes it back
in the response header.  If the caller already provides X-Request-ID we
re-use that value (useful for distributed tracing across services).

The request ID is injected into log records via a LoggerAdapter so that all
log lines emitted during a single request carry the same request_id field,
making it trivial to correlate logs in Cloud Logging.

Usage (FastAPI):
    from shared.middleware.request_id import RequestIDMiddleware
    app.add_middleware(RequestIDMiddleware)
"""

import logging
import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

REQUEST_ID_HEADER = "X-Request-ID"

# Context variable so request_id is available anywhere in the call stack
_request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")


def get_request_id() -> str:
    """Return the current request's ID (available inside a request context)."""
    return _request_id_ctx.get()


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Attach a unique request ID to every request and response."""

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        token = _request_id_ctx.set(request_id)

        try:
            response: Response = await call_next(request)
        finally:
            _request_id_ctx.reset(token)

        response.headers[REQUEST_ID_HEADER] = request_id
        return response


class RequestIDLogFilter(logging.Filter):
    """Inject request_id into every LogRecord while inside a request context."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()  # type: ignore[attr-defined]
        return True
