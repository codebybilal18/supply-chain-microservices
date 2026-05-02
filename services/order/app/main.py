"""Order Service FastAPI application."""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.database import engine
from app.logging_config import setup_logging
from app.routers import health, orders
from shared.middleware.rate_limit import RateLimitMiddleware
from shared.middleware.request_id import RequestIDMiddleware

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("Starting %s v%s", settings.SERVICE_NAME, settings.SERVICE_VERSION)

    # Pub/Sub publisher (wired only when GCP_PROJECT_ID is set)
    app.state.pubsub_publisher = None
    if settings.GCP_PROJECT_ID:
        try:
            from shared.pubsub.publisher import publish_event
            project_id = settings.GCP_PROJECT_ID
            topic = settings.PUBSUB_TOPIC_ORDER_EVENTS

            def _publisher(envelope):
                publish_event(topic, envelope, project_id)

            app.state.pubsub_publisher = _publisher

            # Start fulfillment event subscribers
            from app.subscribers.fulfillment_assigned import FulfillmentAssignedSubscriber
            from app.subscribers.fulfillment_completed import FulfillmentCompletedSubscriber

            sub_assigned = FulfillmentAssignedSubscriber(project_id=settings.GCP_PROJECT_ID)
            sub_assigned.start()

            sub_completed = FulfillmentCompletedSubscriber(project_id=settings.GCP_PROJECT_ID)
            sub_completed.start()

            app.state.pubsub_subscribers = [sub_assigned, sub_completed]
        except Exception as exc:
            logger.warning("Pub/Sub not configured: %s", exc)

    yield

    logger.info("Shutting down %s", settings.SERVICE_NAME)
    for sub in getattr(app.state, "pubsub_subscribers", []):
        sub.stop()
    await engine.dispose()
    logger.info("Shutdown complete.")


app = FastAPI(
    title="SupplyChainForge — Order Service",
    description=(
        "## Order Service\n\n"
        "Handles the complete order lifecycle for the SupplyChainForge platform.\n\n"
        "### Responsibilities\n"
        "- Order creation with inventory validation (sync HTTP to Inventory Service)\n"
        "- Stock reservation orchestration via `POST /reserve` on Inventory Service\n"
        "- Order status machine: `PENDING → CONFIRMED → PROCESSING → SHIPPED → DELIVERED`\n"
        "- Order cancellation with stock release\n"
        "- Pub/Sub publisher: `order.created` on successful confirmation\n"
        "- Pub/Sub subscriber: `fulfillment.assigned` → transition to `PROCESSING`\n"
        "- Pub/Sub subscriber: `fulfillment.completed` → transition to `DELIVERED`\n\n"
        "### Event Flow\n"
        "```\n"
        "POST /orders → order.created (published)\n"
        "fulfillment.assigned (consumed) → status: PROCESSING\n"
        "fulfillment.completed (consumed) → status: DELIVERED\n"
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
            "name": "orders",
            "description": "Order lifecycle management.",
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
app.include_router(orders.router, prefix="/api/v1")
