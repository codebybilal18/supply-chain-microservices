"""
Redis-backed sliding-window rate limiter middleware.

Algorithm: sliding-window counter using a Redis sorted set.
  - Key: "rl:{client_key}" where client_key is the client IP address.
  - Each request adds an entry with score = current epoch timestamp (ms).
  - Entries older than `window_seconds` are trimmed before counting.
  - If count > max_requests, the request is rejected with 429.

Why sorted set instead of a simple counter?
  - True sliding window — no burst allowed at window boundary resets.
  - Atomic via a Redis pipeline (ZADD + ZREMRANGEBYSCORE + ZCARD + EXPIRE).

Design decisions:
  - Best-effort: if Redis is unreachable the rate limiter is bypassed (does
    not block traffic, just stops enforcing limits).
  - Whitelists /health endpoints so health checks are never throttled.
  - Returns standard Retry-After header.

Usage (FastAPI):
    from shared.middleware.rate_limit import RateLimitMiddleware
    app.add_middleware(
        RateLimitMiddleware,
        redis_url="redis://localhost:6379/0",
        max_requests=100,
        window_seconds=60,
    )
"""

import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

# Paths that are always exempt from rate limiting
_EXEMPT_PATHS = {"/health", "/health/ready", "/health/live"}


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window rate limiter backed by Redis."""

    def __init__(
        self,
        app,
        redis_url: str = "redis://localhost:6379/0",
        max_requests: int = 100,
        window_seconds: int = 60,
    ) -> None:
        super().__init__(app)
        self._redis_url = redis_url
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._client = None
        self._enabled = True

    async def _get_client(self):
        """Lazy-initialise the async Redis client (best-effort)."""
        if self._client is not None:
            return self._client
        try:
            import redis.asyncio as aioredis

            self._client = await aioredis.from_url(
                self._redis_url, encoding="utf-8", decode_responses=True
            )
        except Exception as exc:
            logger.warning("RateLimitMiddleware: Redis unavailable, disabling: %s", exc)
            self._enabled = False
        return self._client

    async def dispatch(self, request: Request, call_next) -> Response:
        # Skip rate limiting for health checks
        if request.url.path in _EXEMPT_PATHS:
            return await call_next(request)

        if not self._enabled:
            return await call_next(request)

        client_ip = self._get_client_ip(request)
        try:
            allowed, remaining, retry_after = await self._check_limit(client_ip)
        except Exception as exc:
            logger.warning("RateLimitMiddleware: check failed, bypassing: %s", exc)
            return await call_next(request)

        if not allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Too many requests. Please slow down.",
                    "retry_after_seconds": retry_after,
                },
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(self._max_requests),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(time.time()) + retry_after),
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self._max_requests)
        response.headers["X-RateLimit-Remaining"] = str(max(0, remaining))
        response.headers["X-RateLimit-Reset"] = str(
            int(time.time()) + self._window_seconds
        )
        return response

    async def _check_limit(self, client_ip: str) -> tuple[bool, int, int]:
        """
        Apply sliding window counter.
        Returns: (allowed, remaining_requests, retry_after_seconds)
        """
        redis = await self._get_client()
        if redis is None:
            return True, self._max_requests, 0

        now_ms = int(time.time() * 1000)
        window_ms = self._window_seconds * 1000
        key = f"rl:{client_ip}"

        pipe = redis.pipeline()
        pipe.zremrangebyscore(key, 0, now_ms - window_ms)  # remove expired
        pipe.zadd(key, {str(now_ms): now_ms})               # add current
        pipe.zcard(key)                                      # count in window
        pipe.expire(key, self._window_seconds + 1)           # TTL cleanup
        results = await pipe.execute()

        count: int = results[2]
        remaining = self._max_requests - count
        allowed = count <= self._max_requests
        retry_after = self._window_seconds if not allowed else 0
        return allowed, remaining, retry_after

    @staticmethod
    def _get_client_ip(request: Request) -> str:
        """Extract real client IP, honouring X-Forwarded-For from Cloud Run / load balancer."""
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # Take the first (leftmost) IP — that's the original client
            return forwarded_for.split(",")[0].strip()
        if request.client:
            return request.client.host
        return "unknown"
