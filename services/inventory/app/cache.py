"""
Redis cache client for the Inventory Service.

Design:
  - Uses redis.asyncio (same package as redis-py, async variant) so cache
    hits/misses don't block FastAPI's event loop.
  - Singleton client created at startup and closed at shutdown.
  - All keys are prefixed with "inv:" to avoid collisions if Redis is shared.
  - TTLs are intentionally short for stock data (60 s) because stock counts
    change frequently; product metadata (name, price) can cache longer (5 min).
  - Cache-aside pattern: read from cache → on miss, read DB → write cache.
  - Any Redis error falls through silently (cache is best-effort).
"""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

KEY_PREFIX = "inv:"
PRODUCT_TTL = 300       # 5 minutes — product metadata
STOCK_TTL = 60          # 1 minute  — stock counts (hot data)
LIST_TTL = 30           # 30 seconds — list results


def _product_key(product_id: int) -> str:
    return f"{KEY_PREFIX}product:{product_id}"


def _product_sku_key(sku: str) -> str:
    return f"{KEY_PREFIX}sku:{sku}"


def _list_key(page: int, page_size: int, category: str | None, low_stock_only: bool) -> str:
    cat = category or "all"
    ls = "1" if low_stock_only else "0"
    return f"{KEY_PREFIX}list:{page}:{page_size}:{cat}:{ls}"


class CacheService:
    """Async Redis cache operations for inventory data."""

    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url
        self._client = None

    async def connect(self) -> None:
        import redis.asyncio as aioredis
        self._client = await aioredis.from_url(
            self._redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
        logger.info("Redis cache connected url=%s", self._redis_url)

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            logger.info("Redis cache closed")

    async def ping(self) -> bool:
        """Return True if Redis is reachable."""
        if not self._client:
            return False
        try:
            return await self._client.ping()
        except Exception:
            return False

    async def get_product(self, product_id: int) -> dict | None:
        return await self._get(_product_key(product_id))

    async def set_product(self, product_id: int, data: dict) -> None:
        await self._set(_product_key(product_id), data, ttl=PRODUCT_TTL)
        # Also cache by SKU
        if "sku" in data:
            await self._set(_product_sku_key(data["sku"]), data, ttl=PRODUCT_TTL)

    async def invalidate_product(self, product_id: int, sku: str | None = None) -> None:
        await self._delete(_product_key(product_id))
        if sku:
            await self._delete(_product_sku_key(sku))
        # Invalidate all list caches when product changes
        await self._delete_pattern(f"{KEY_PREFIX}list:*")

    async def get_list(
        self, page: int, page_size: int, category: str | None, low_stock_only: bool
    ) -> dict | None:
        return await self._get(_list_key(page, page_size, category, low_stock_only))

    async def set_list(
        self, page: int, page_size: int, category: str | None, low_stock_only: bool, data: dict
    ) -> None:
        await self._set(_list_key(page, page_size, category, low_stock_only), data, ttl=LIST_TTL)

    # ── Low-level helpers ─────────────────────────────────────────────────────

    async def _get(self, key: str) -> dict | None:
        if not self._client:
            return None
        try:
            raw = await self._client.get(key)
            if raw:
                return json.loads(raw)
        except Exception as exc:
            logger.warning("Cache GET error key=%s: %s", key, exc)
        return None

    async def _set(self, key: str, value: dict, ttl: int) -> None:
        if not self._client:
            return
        try:
            await self._client.setex(key, ttl, json.dumps(value, default=str))
        except Exception as exc:
            logger.warning("Cache SET error key=%s: %s", key, exc)

    async def _delete(self, key: str) -> None:
        if not self._client:
            return
        try:
            await self._client.delete(key)
        except Exception as exc:
            logger.warning("Cache DEL error key=%s: %s", key, exc)

    async def _delete_pattern(self, pattern: str) -> None:
        if not self._client:
            return
        try:
            keys = await self._client.keys(pattern)
            if keys:
                await self._client.delete(*keys)
        except Exception as exc:
            logger.warning("Cache DEL pattern=%s error: %s", pattern, exc)
