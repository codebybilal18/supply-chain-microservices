"""
SupplyChainForge — Inventory Service entry point.

Startup sequence:
  1. Logging is configured (JSON structured, stdout).
  2. The async engine is created (connection pool is lazy — no connections
     are opened until the first request).
  3. FastAPI registers routes and middleware.
  4. Uvicorn serves on 0.0.0.0:8000.

Shutdown sequence:
  - The lifespan context manager disposes the engine, draining the pool
    gracefully before the process exits.
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.cache import CacheService
from app.config import settings
from app.database import engine
from app.logging_config import setup_logging
from app.routers import health, products

# Configure logging before any other module uses the logger
setup_logging()
logger = logging.getLogger(__name__)


# ── Lifespan (startup / shutdown) ─────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # ── Startup ───────────────────────────────────────────────────────────────
    logger.info(
        "Starting %s v%s (debug=%s)",
        settings.SERVICE_NAME, settings.SERVICE_VERSION, settings.DEBUG,
    )

    # Redis cache (best-effort — service still works without Redis)
    cache = CacheService(settings.redis_url)
    try:
        await cache.connect()
    except Exception as exc:
        logger.warning("Redis not available, running without cache: %s", exc)
    app.state.cache = cache

    # Pub/Sub subscriber for order.created events (starts background thread)
    if settings.GCP_PROJECT_ID:
        try:
            from app.subscribers.order_created import OrderCreatedSubscriber
            sub = OrderCreatedSubscriber(project_id=settings.GCP_PROJECT_ID)
            sub.start()
            app.state.pubsub_subscriber = sub
        except Exception as exc:
            logger.warning("Pub/Sub subscriber not started: %s", exc)

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    logger.info("Shutting down %s", settings.SERVICE_NAME)
    await cache.close()
    if hasattr(app.state, "pubsub_subscriber"):
        app.state.pubsub_subscriber.stop()
    await engine.dispose()
    logger.info("Shutdown complete.")


# ── Application factory ───────────────────────────────────────────────────────

app = FastAPI(
    title="SupplyChainForge — Inventory Service",
    description=(
        "Manages products, stock levels, and reservations. "
        "Part of the SupplyChainForge microservice platform."
    ),
    version=settings.SERVICE_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# ── Middleware ────────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    # Restrict origins in production via environment variable (Phase 4)
    allow_origins=["*"] if settings.DEBUG else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Global exception handler ──────────────────────────────────────────────────

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Catch-all for unexpected errors.
    Logs the full traceback internally but returns a safe generic message
    to clients (no stack traces in responses — OWASP A05).
    """
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An unexpected error occurred. Please try again later."},
    )


# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(health.router)                        # /health, /health/ready
app.include_router(products.router, prefix="/api/v1")   # /api/v1/products/...
