"""
Subscriber: order.created → create Fulfillment record and assign warehouse.

Idempotency: uses the ProcessedEvent table to guard against double-processing.
"""

import asyncio
import logging
from typing import Callable, Optional

from shared.events.envelope import EventEnvelope
from shared.events.order_events import ORDER_CREATED, OrderCreatedData
from shared.pubsub.subscriber import PullSubscriber

from app.config import settings

logger = logging.getLogger(__name__)


class OrderCreatedSubscriber(PullSubscriber):
    subscription_id = settings.PUBSUB_SUBSCRIPTION_ORDER_CREATED

    def __init__(self, project_id: str, publisher: Optional[Callable] = None, **kwargs):
        super().__init__(project_id=project_id, **kwargs)
        self._publisher = publisher

    def handle(self, envelope: EventEnvelope) -> None:
        if envelope.event_type != ORDER_CREATED:
            return
        data = OrderCreatedData(**envelope.data)
        logger.info("Received order.created order_id=%d", data.order_id)
        asyncio.run(self._create_fulfillment(data, envelope.event_id))

    async def _create_fulfillment(self, data: OrderCreatedData, event_id: str) -> None:
        from app.database import AsyncSessionLocal
        from app.services.fulfillment_service import FulfillmentService
        from shared.db.idempotency import is_already_processed, mark_processed

        async with AsyncSessionLocal() as session:
            if await is_already_processed(session, settings.SERVICE_NAME, event_id):
                logger.info(
                    "order.created event_id=%s already processed, skipping", event_id
                )
                return

            try:
                service = FulfillmentService(
                    db=session, pubsub_publisher=self._publisher
                )
                await service.create_from_order(
                    order_id=data.order_id,
                    customer_id=data.customer_id,
                    shipping_address=data.shipping_address,
                    warehouse_hint=data.warehouse_hint,
                )
                await mark_processed(session, settings.SERVICE_NAME, event_id)
                await session.commit()
            except Exception:
                await session.rollback()
                logger.exception("Failed to create fulfillment for order_id=%d", data.order_id)
                raise

