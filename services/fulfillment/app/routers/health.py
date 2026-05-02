"""Health endpoints for Fulfillment Service."""

import logging
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.config import settings
from app.dependencies import get_db

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


@router.get("/health", summary="Liveness probe")
async def liveness() -> dict:
    return {"status": "alive", "service": settings.SERVICE_NAME, "version": settings.SERVICE_VERSION}


@router.get("/health/live", summary="Liveness probe (explicit path)")
async def liveness_explicit() -> dict:
    return {"status": "alive", "service": settings.SERVICE_NAME, "version": settings.SERVICE_VERSION}


@router.get("/health/ready", summary="Readiness probe")
async def readiness(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    try:
        await db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as exc:
        logger.error("Readiness check — DB failed: %s", exc)
        db_status = "disconnected"

    redis_status = "unavailable"
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.redis_url, socket_timeout=1)
        if await r.ping():
            redis_status = "connected"
        await r.aclose()
    except Exception as exc:
        logger.warning("Readiness check — Redis failed: %s", exc)

    return {
        "status": "ready" if db_status == "connected" else "not_ready",
        "service": settings.SERVICE_NAME,
        "version": settings.SERVICE_VERSION,
        "dependencies": {"database": db_status, "redis": redis_status},
    }
