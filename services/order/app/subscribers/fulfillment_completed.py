"""
Subscriber: fulfillment.completed → transition order to COMPLETED.

When a fulfillment completes (items shipped and delivered), the corresponding
order should be marked COMPLETED.

Idempotency: uses the ProcessedEvent table to guard against double-processing.
"""

import asyncio
import logging

from shared.events.envelope import EventEnvelope
from shared.events.fulfillment_events import FULFILLMENT_COMPLETED, FulfillmentCompletedData
from shared.pubsub.subscriber import PullSubscriber

from app.config import settings

logger = logging.getLogger(__name__)


class FulfillmentCompletedSubscriber(PullSubscriber):
    subscription_id = settings.PUBSUB_SUBSCRIPTION_FULFILLMENT_COMPLETED

    def handle(self, envelope: EventEnvelope) -> None:
        if envelope.event_type != FULFILLMENT_COMPLETED:
            return

        data = FulfillmentCompletedData(**envelope.data)
        logger.info(
            "Received fulfillment.completed order_id=%d fulfillment_id=%d tracking=%s",
            data.order_id, data.fulfillment_id, data.tracking_number,
        )
        asyncio.run(self._complete_order(data, envelope.event_id))

    async def _complete_order(
        self, data: FulfillmentCompletedData, event_id: str
    ) -> None:
        from app.database import AsyncSessionLocal
        from app.models.order import OrderStatus
        from app.services.order_service import OrderService
        from app.config import settings as cfg
        from shared.db.idempotency import is_already_processed, mark_processed

        async with AsyncSessionLocal() as session:
            if await is_already_processed(session, settings.SERVICE_NAME, event_id):
                logger.info(
                    "fulfillment.completed event_id=%s already processed, skipping",
                    event_id,
                )
                return

            try:
                service = OrderService(
                    db=session,
                    inventory_base_url=cfg.INVENTORY_SERVICE_URL,
                )
                await service.update_status(data.order_id, OrderStatus.DELIVERED)
                await mark_processed(session, settings.SERVICE_NAME, event_id)
                await session.commit()
                logger.info(
                    "Marked order_id=%d as COMPLETED (fulfillment_id=%d)",
                    data.order_id, data.fulfillment_id,
                )
            except Exception:
                await session.rollback()
                logger.exception(
                    "Failed to complete order_id=%d — NACK", data.order_id
                )
                raise
