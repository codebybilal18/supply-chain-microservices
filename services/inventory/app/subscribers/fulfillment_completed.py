"""
Subscriber: fulfillment.completed → mark reservation as consumed.

When a fulfillment completes, reserved stock transitions from "reserved"
(awaiting shipment) to "shipped" (physically left warehouse).  This means:
  - quantity_reserved decreases by the order quantity
  - quantity_available decreases by the order quantity
  (net effect: reserved units are no longer counted as on-hand)

Because fulfillment.completed does not carry item-level quantity data,
this subscriber records the event for audit/idempotency purposes and logs
the completion.  Full stock deduction via carry-along item data is a
planned enhancement once the fulfillment event schema is extended.

Idempotency: uses the ProcessedEvent table.
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
        asyncio.run(self._record_completion(data, envelope.event_id))

    async def _record_completion(
        self, data: FulfillmentCompletedData, event_id: str
    ) -> None:
        from app.database import AsyncSessionLocal
        from shared.db.idempotency import is_already_processed, mark_processed

        async with AsyncSessionLocal() as session:
            if await is_already_processed(session, settings.SERVICE_NAME, event_id):
                logger.info(
                    "fulfillment.completed event_id=%s already processed, skipping",
                    event_id,
                )
                return

            try:
                await mark_processed(session, settings.SERVICE_NAME, event_id)
                await session.commit()
                logger.info(
                    "Recorded fulfillment completion order_id=%d", data.order_id
                )
            except Exception:
                await session.rollback()
                logger.exception(
                    "Failed to record fulfillment completion order_id=%d", data.order_id
                )
                raise

