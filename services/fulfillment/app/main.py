"""Fulfillment Service FastAPI application."""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.database import engine
from app.logging_config import setup_logging
from app.routers import health, fulfillments
from shared.middleware.rate_limit import RateLimitMiddleware
from shared.middleware.request_id import RequestIDMiddleware

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("Starting %s v%s", settings.SERVICE_NAME, settings.SERVICE_VERSION)

    app.state.pubsub_publisher = None
    if settings.GCP_PROJECT_ID:
        try:
            from shared.pubsub.publisher import publish_event
            project_id = settings.GCP_PROJECT_ID
            topic = settings.PUBSUB_TOPIC_FULFILLMENT_EVENTS

            def _publisher(envelope):
                publish_event(topic, envelope, project_id)

            app.state.pubsub_publisher = _publisher

            from app.subscribers.order_created import OrderCreatedSubscriber
            sub = OrderCreatedSubscriber(
                project_id=settings.GCP_PROJECT_ID, publisher=_publisher
            )
            sub.start()
            app.state.pubsub_subscribers = [sub]
        except Exception as exc:
            logger.warning("Pub/Sub not configured: %s", exc)

    yield

    logger.info("Shutting down %s", settings.SERVICE_NAME)
    for sub in getattr(app.state, "pubsub_subscribers", []):
        sub.stop()
    await engine.dispose()
    logger.info("Shutdown complete.")


app = FastAPI(
    title="SupplyChainForge — Fulfillment Service",
    description=(
        "## Fulfillment Service\n\n"
        "Handles warehouse assignment, picking, and shipping for the "
        "SupplyChainForge platform.\n\n"
        "### Responsibilities\n"
        "- Automatic warehouse assignment on order arrival\n"
        "- Fulfillment state machine: `ASSIGNED → PICKING → SHIPPED → COMPLETED`\n"
        "- Carrier simulation (FedEx / UPS / DHL random assignment)\n"
        "- Pub/Sub subscriber: `order.created` → create fulfillment record\n"
        "- Pub/Sub publisher: `fulfillment.assigned` after warehouse assignment\n"
        "- Pub/Sub publisher: `fulfillment.completed` after delivery confirmation\n\n"
        "### Event Flow\n"
        "```\n"
        "order.created (consumed) → fulfillment.assigned (published)\n"
        "POST /complete    → fulfillment.completed (published)\n"
        "```\n\n"
        "### Authentication\n"
        "Internal service — no public authentication in this version."
    ),
    version=settings.SERVICE_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    openapi_tags=[
        {
            "name": "fulfillments",
            "description": "Fulfillment lifecycle: warehouse → pick → ship → complete.",
        },
        {
            "name": "health",
            "description": "Liveness and readiness probes.",
        },
    ],
    contact={
        "name": "SupplyChainForge Engineering",
        "url": "https://github.com/your-org/supply-chain-forge",
    },
    license_info={"name": "MIT"},
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.DEBUG else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(RequestIDMiddleware)

if settings.RATE_LIMIT_ENABLED:
    app.add_middleware(
        RateLimitMiddleware,
        redis_url=settings.redis_url,
        max_requests=settings.RATE_LIMIT_REQUESTS,
        window_seconds=settings.RATE_LIMIT_WINDOW,
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An unexpected error occurred. Please try again later."},
    )


app.include_router(health.router)
app.include_router(fulfillments.router, prefix="/api/v1")
