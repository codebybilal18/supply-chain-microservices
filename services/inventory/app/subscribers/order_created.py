"""
Subscriber: order.created → reserve stock for each order item, then publish
inventory.stock_reserved so downstream services know the reservation succeeded.

Idempotency: duplicate order.created messages are handled at the DB level via
the ProcessedEvent table (see shared.db.idempotency).  The reservation itself
is also idempotent via the `reservations` check in InventoryService.
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
            return  # ignore unrelated events on shared subscriptions

        order_data = OrderCreatedData(**envelope.data)
        logger.info(
            "Received order.created order_id=%d items=%d",
            order_data.order_id, len(order_data.items),
        )

        asyncio.run(self._reserve_all(order_data, envelope.event_id))

    async def _reserve_all(self, order_data: OrderCreatedData, event_id: str) -> None:
        from app.database import AsyncSessionLocal
        from app.services.inventory_service import InventoryService
        from shared.db.idempotency import is_already_processed, mark_processed

        async with AsyncSessionLocal() as session:
            # Idempotency check — skip if this event was already processed
            if await is_already_processed(session, settings.SERVICE_NAME, event_id):
                logger.info(
                    "order.created event_id=%s already processed, skipping", event_id
                )
                return

            try:
                service = InventoryService(db=session)
                for item in order_data.items:
                    await service.reserve_stock(
                        product_id=item.product_id,
                        quantity=item.quantity,
                        order_id=str(order_data.order_id),
                    )

                await mark_processed(session, settings.SERVICE_NAME, event_id)
                await session.commit()

                logger.info(
                    "Reserved all items for order_id=%d", order_data.order_id
                )
                self._publish_stock_reserved(order_data)
            except Exception:
                await session.rollback()
                logger.exception(
                    "Failed to reserve stock for order_id=%d — NACK",
                    order_data.order_id,
                )
                raise

    def _publish_stock_reserved(self, order_data: OrderCreatedData) -> None:
        if not self._publisher:
            return
        try:
            from shared.events.inventory_events import STOCK_RESERVED
            envelope = EventEnvelope(
                event_type=STOCK_RESERVED,
                source=settings.SERVICE_NAME,
                data={
                    "order_id": order_data.order_id,
                    "reservations": [
                        {
                            "product_id": item.product_id,
                            "sku": item.sku,
                            "quantity": item.quantity,
                        }
                        for item in order_data.items
                    ],
                },
            )
            self._publisher(envelope)
            logger.info("Published stock_reserved for order_id=%d", order_data.order_id)
        except Exception:
            logger.exception(
                "Failed to publish stock_reserved for order_id=%d", order_data.order_id
            )
