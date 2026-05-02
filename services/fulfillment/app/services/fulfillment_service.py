"""
Fulfillment business-logic service.

Responsibilities:
  - Create a fulfillment record when an order.created event arrives
  - Assign to a warehouse (simulated)
  - Progress through picking → shipped → completed
  - Publish fulfillment.assigned and fulfillment.completed events
"""

import hashlib
import logging
import math
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import FulfillmentNotFoundError, InvalidFulfillmentStateError
from app.models.fulfillment import Fulfillment, FulfillmentStatus
from app.schemas.fulfillment import AssignWarehouseRequest, MarkShippedRequest

logger = logging.getLogger(__name__)

WAREHOUSES = ["warehouse-east", "warehouse-west", "warehouse-central"]
CARRIERS = ["fedex", "ups", "dhl"]


def _select_warehouse(order_id: int, hint: Optional[str] = None) -> str:
    """Deterministic warehouse selection for reproducibility in tests."""
    if hint and hint in WAREHOUSES:
        return hint
    return WAREHOUSES[order_id % len(WAREHOUSES)]


def _select_carrier(order_id: int) -> str:
    return CARRIERS[order_id % len(CARRIERS)]


class FulfillmentService:
    def __init__(self, db: AsyncSession, pubsub_publisher=None) -> None:
        self._db = db
        self._publisher = pubsub_publisher

    # ── Create ────────────────────────────────────────────────────────────────

    async def create_from_order(
        self,
        order_id: int,
        customer_id: str,
        shipping_address: Optional[str] = None,
        warehouse_hint: Optional[str] = None,
    ) -> Fulfillment:
        """
        Idempotent: if a fulfillment already exists for this order, return it.
        This handles duplicate order.created events.
        """
        existing = await self._db.scalar(
            select(Fulfillment).where(Fulfillment.order_id == order_id)
        )
        if existing:
            logger.info("Fulfillment already exists for order_id=%d, skipping", order_id)
            return existing

        warehouse = _select_warehouse(order_id, warehouse_hint)
        carrier = _select_carrier(order_id)

        fulfillment = Fulfillment(
            order_id=order_id,
            customer_id=customer_id,
            status=FulfillmentStatus.ASSIGNED.value,
            warehouse_id=warehouse,
            carrier=carrier,
            shipping_address=shipping_address,
        )
        self._db.add(fulfillment)
        await self._db.flush()

        logger.info(
            "Created fulfillment id=%d for order_id=%d warehouse=%s",
            fulfillment.id, order_id, warehouse,
        )
        self._publish_fulfillment_assigned(fulfillment)
        return fulfillment

    # ── Read ──────────────────────────────────────────────────────────────────

    async def get_fulfillment(self, fulfillment_id: int) -> Fulfillment:
        result = await self._db.execute(
            select(Fulfillment).where(Fulfillment.id == fulfillment_id)
        )
        f = result.scalar_one_or_none()
        if f is None:
            raise FulfillmentNotFoundError(fulfillment_id)
        return f

    async def get_by_order(self, order_id: int) -> Fulfillment:
        result = await self._db.execute(
            select(Fulfillment).where(Fulfillment.order_id == order_id)
        )
        f = result.scalar_one_or_none()
        if f is None:
            raise FulfillmentNotFoundError(order_id)
        return f

    async def list_fulfillments(
        self,
        page: int = 1,
        page_size: int = 20,
        status: Optional[str] = None,
    ) -> tuple[list[Fulfillment], int]:
        base = select(Fulfillment)
        count_q = select(func.count()).select_from(Fulfillment)
        if status:
            base = base.where(Fulfillment.status == status)
            count_q = count_q.where(Fulfillment.status == status)
        total: int = await self._db.scalar(count_q) or 0
        result = await self._db.execute(
            base.order_by(Fulfillment.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(result.scalars().all()), total

    # ── State transitions ─────────────────────────────────────────────────────

    async def start_picking(self, fulfillment_id: int) -> Fulfillment:
        f = await self.get_fulfillment(fulfillment_id)
        if not f.can_transition_to(FulfillmentStatus.PICKING):
            raise InvalidFulfillmentStateError(fulfillment_id, f.status, "start picking")
        f.status = FulfillmentStatus.PICKING.value
        f.version += 1
        await self._db.flush()
        return f

    async def mark_shipped(self, fulfillment_id: int, req: MarkShippedRequest) -> Fulfillment:
        f = await self.get_fulfillment(fulfillment_id)
        if not f.can_transition_to(FulfillmentStatus.SHIPPED):
            raise InvalidFulfillmentStateError(fulfillment_id, f.status, "mark shipped")
        f.status = FulfillmentStatus.SHIPPED.value
        f.tracking_number = req.tracking_number
        if req.carrier:
            f.carrier = req.carrier
        f.version += 1
        await self._db.flush()
        return f

    async def mark_completed(self, fulfillment_id: int) -> Fulfillment:
        f = await self.get_fulfillment(fulfillment_id)
        if not f.can_transition_to(FulfillmentStatus.COMPLETED):
            raise InvalidFulfillmentStateError(fulfillment_id, f.status, "complete")
        f.status = FulfillmentStatus.COMPLETED.value
        f.version += 1
        await self._db.flush()
        self._publish_fulfillment_completed(f)
        return f

    async def mark_failed(self, fulfillment_id: int, reason: str) -> Fulfillment:
        f = await self.get_fulfillment(fulfillment_id)
        if not f.can_transition_to(FulfillmentStatus.FAILED):
            raise InvalidFulfillmentStateError(fulfillment_id, f.status, "fail")
        f.status = FulfillmentStatus.FAILED.value
        f.failure_reason = reason
        f.version += 1
        await self._db.flush()
        return f

    # ── Private helpers ───────────────────────────────────────────────────────

    def _publish_fulfillment_assigned(self, f: Fulfillment) -> None:
        if not self._publisher:
            return
        try:
            from shared.events.envelope import EventEnvelope
            from shared.events.fulfillment_events import FULFILLMENT_ASSIGNED
            envelope = EventEnvelope(
                event_type=FULFILLMENT_ASSIGNED,
                source="fulfillment-service",
                data={
                    "fulfillment_id": f.id,
                    "order_id": f.order_id,
                    "customer_id": f.customer_id,
                    "warehouse_id": f.warehouse_id,
                    "carrier": f.carrier,
                },
            )
            self._publisher(envelope)
        except Exception:
            logger.exception("Failed to publish fulfillment.assigned event id=%d", f.id)

    def _publish_fulfillment_completed(self, f: Fulfillment) -> None:
        if not self._publisher:
            return
        try:
            from shared.events.envelope import EventEnvelope
            from shared.events.fulfillment_events import FULFILLMENT_COMPLETED
            envelope = EventEnvelope(
                event_type=FULFILLMENT_COMPLETED,
                source="fulfillment-service",
                data={
                    "fulfillment_id": f.id,
                    "order_id": f.order_id,
                    "customer_id": f.customer_id,
                    "tracking_number": f.tracking_number,
                    "carrier": f.carrier,
                },
            )
            self._publisher(envelope)
        except Exception:
            logger.exception("Failed to publish fulfillment.completed event id=%d", f.id)
