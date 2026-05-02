"""
Health-check endpoints.

Two endpoints following the Kubernetes/Cloud Run convention:
  GET /health        — liveness probe  (is the process alive?)
  GET /health/live   — alias for /health (explicit liveness path)
  GET /health/ready  — readiness probe (can it serve traffic?)

Cloud Run uses the readiness probe to decide when to route requests.
The liveness probe determines when to restart a container.
"""

import logging

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.config import settings
from app.dependencies import get_db

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


@router.get(
    "/health",
    summary="Liveness probe",
    description="Returns 200 if the process is running.",
)
async def liveness() -> dict:
    return {
        "status": "alive",
        "service": settings.SERVICE_NAME,
        "version": settings.SERVICE_VERSION,
    }


@router.get(
    "/health/live",
    summary="Liveness probe (explicit path)",
    description="Alias for /health — returns 200 if the process is running.",
)
async def liveness_explicit() -> dict:
    return {
        "status": "alive",
        "service": settings.SERVICE_NAME,
        "version": settings.SERVICE_VERSION,
    }


@router.get(
    "/health/ready",
    summary="Readiness probe",
    description="Returns 200 only when all dependencies are healthy.",
)
async def readiness(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    # Database check
    try:
        await db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as exc:
        logger.error("Readiness check — DB failed: %s", exc)
        db_status = "disconnected"

    # Redis check (optional dependency — service still works without cache)
    redis_status = "unavailable"
    try:
        cache = getattr(request.app.state, "cache", None)
        if cache and await cache.ping():
            redis_status = "connected"
    except Exception as exc:
        logger.warning("Readiness check — Redis failed: %s", exc)

    is_ready = db_status == "connected"
    return {
        "status": "ready" if is_ready else "not_ready",
        "service": settings.SERVICE_NAME,
        "version": settings.SERVICE_VERSION,
        "dependencies": {
            "database": db_status,
            "redis": redis_status,
        },
    }
