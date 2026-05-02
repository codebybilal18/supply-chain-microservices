"""
Health-check endpoints.

Two endpoints following the Kubernetes/Cloud Run convention:
  GET /health        — liveness probe  (is the process alive?)
  GET /health/ready  — readiness probe (can it serve traffic?)

Cloud Run uses the readiness probe to decide when to route requests.
The liveness probe determines when to restart a container.
"""

import logging

from fastapi import APIRouter, Depends, status
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
    "/health/ready",
    summary="Readiness probe",
    description="Returns 200 only when the database connection is healthy.",
)
async def readiness(db: AsyncSession = Depends(get_db)) -> dict:
    try:
        await db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as exc:
        logger.error("Readiness check failed: %s", exc)
        db_status = "disconnected"

    is_ready = db_status == "connected"
    return {
        "status": "ready" if is_ready else "not_ready",
        "service": settings.SERVICE_NAME,
        "version": settings.SERVICE_VERSION,
        "dependencies": {
            "database": db_status,
        },
    }
