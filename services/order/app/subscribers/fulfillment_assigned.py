"""
Subscriber: fulfillment.assigned → transition order to PROCESSING.
"""

import asyncio
import logging

from shared.events.envelope import EventEnvelope
from shared.events.fulfillment_events import FULFILLMENT_ASSIGNED, FulfillmentAssignedData
from shared.pubsub.subscriber import PullSubscriber

from app.config import settings

logger = logging.getLogger(__name__)


class FulfillmentAssignedSubscriber(PullSubscriber):
    subscription_id = settings.PUBSUB_SUBSCRIPTION_FULFILLMENT_ASSIGNED

    def handle(self, envelope: EventEnvelope) -> None:
        if envelope.event_type != FULFILLMENT_ASSIGNED:
            return

        data = FulfillmentAssignedData(**envelope.data)
        logger.info(
            "Received fulfillment.assigned order_id=%d fulfillment_id=%d",
            data.order_id, data.fulfillment_id,
        )
        asyncio.run(self._update_order(data.order_id, envelope.event_id))

    async def _update_order(self, order_id: int, event_id: str) -> None:
        from app.database import AsyncSessionLocal
        from app.models.order import OrderStatus
        from app.services.order_service import OrderService
        from app.config import settings as cfg
        from shared.db.idempotency import is_already_processed, mark_processed

        async with AsyncSessionLocal() as session:
            if await is_already_processed(session, settings.SERVICE_NAME, event_id):
                logger.info(
                    "fulfillment.assigned event_id=%s already processed, skipping",
                    event_id,
                )
                return

            try:
                service = OrderService(
                    db=session,
                    inventory_base_url=cfg.INVENTORY_SERVICE_URL,
                )
                await service.update_status(order_id, OrderStatus.PROCESSING)
                await mark_processed(session, settings.SERVICE_NAME, event_id)
                await session.commit()
            except Exception:
                await session.rollback()
                logger.exception("Failed to update order_id=%d to PROCESSING", order_id)
                raise
