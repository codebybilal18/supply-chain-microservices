"""
Subscriber: order.created → reserve stock for each order item.

This subscriber runs in a background thread (see PullSubscriber base class).
On receiving an order.created event it:
  1. Opens a new DB session (cannot reuse the request-scoped session).
  2. Calls reserve_stock for each item in the order.
  3. Publishes inventory.stock_reserved on success.
  4. ACKs the message only if all reservations succeed.
  5. On any failure, raises (NACK) so the message is redelivered.

Idempotency: if the order_id was already processed, the re-reservation
will fail with InsufficientStockError on items already counted — future
Phase 5 work will add an idempotency table to guard this properly.
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
            return  # ignore unrelated events on shared subscriptions

        order_data = OrderCreatedData(**envelope.data)
        logger.info(
            "Received order.created order_id=%d items=%d",
            order_data.order_id, len(order_data.items),
        )

        # Run async DB operations in a new event loop (subscriber runs in a thread)
        asyncio.run(self._reserve_all(order_data))

    async def _reserve_all(self, order_data: OrderCreatedData) -> None:
        from sqlalchemy.ext.asyncio import AsyncSession
        from app.database import AsyncSessionLocal
        from app.services.inventory_service import InventoryService

        async with AsyncSessionLocal() as session:
            try:
                service = InventoryService(db=session)
                for item in order_data.items:
                    await service.reserve_stock(
                        product_id=item.product_id,
                        quantity=item.quantity,
                        order_id=str(order_data.order_id),
                    )
                await session.commit()
                logger.info(
                    "Reserved all items for order_id=%d", order_data.order_id
                )
            except Exception:
                await session.rollback()
                logger.exception(
                    "Failed to reserve stock for order_id=%d — NACK",
                    order_data.order_id,
                )
                raise
