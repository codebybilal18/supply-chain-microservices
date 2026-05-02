"""Health endpoints for Fulfillment Service."""

import logging
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.config import settings
from app.dependencies import get_db

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


@router.get("/health", summary="Liveness probe")
async def liveness() -> dict:
    return {"status": "alive", "service": settings.SERVICE_NAME, "version": settings.SERVICE_VERSION}


@router.get("/health/ready", summary="Readiness probe")
async def readiness(db: AsyncSession = Depends(get_db)) -> dict:
    try:
        await db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as exc:
        logger.error("Readiness check failed: %s", exc)
        db_status = "disconnected"
    return {
        "status": "ready" if db_status == "connected" else "not_ready",
        "service": settings.SERVICE_NAME,
        "version": settings.SERVICE_VERSION,
        "dependencies": {"database": db_status},
    }
