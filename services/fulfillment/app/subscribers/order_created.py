"""
Subscriber: order.created → create Fulfillment record and assign warehouse.
"""

import asyncio
import logging

from shared.events.envelope import EventEnvelope
from shared.events.order_events import ORDER_CREATED, OrderCreatedData
from shared.pubsub.subscriber import PullSubscriber

from app.config import settings

logger = logging.getLogger(__name__)


class OrderCreatedSubscriber(PullSubscriber):
    subscription_id = settings.PUBSUB_SUBSCRIPTION_ORDER_CREATED

    def handle(self, envelope: EventEnvelope) -> None:
        if envelope.event_type != ORDER_CREATED:
            return
        data = OrderCreatedData(**envelope.data)
        logger.info("Received order.created order_id=%d", data.order_id)
        asyncio.run(self._create_fulfillment(data))

    async def _create_fulfillment(self, data: OrderCreatedData) -> None:
        from app.database import AsyncSessionLocal
        from app.services.fulfillment_service import FulfillmentService

        async with AsyncSessionLocal() as session:
            try:
                service = FulfillmentService(db=session)
                await service.create_from_order(
                    order_id=data.order_id,
                    customer_id=data.customer_id,
                    shipping_address=data.shipping_address,
                    warehouse_hint=data.warehouse_hint,
                )
                await session.commit()
            except Exception:
                await session.rollback()
                logger.exception("Failed to create fulfillment for order_id=%d", data.order_id)
                raise
