"""
Order business-logic service.

Workflow for order creation:
  1. Validate all items exist in Inventory Service (HTTP call).
  2. Create Order + OrderItems in DB (PENDING status).
  3. Reserve stock for each item via Inventory Service (HTTP calls).
  4. Transition Order to CONFIRMED.
  5. Publish order.created event to Pub/Sub.

Rollback on failure:
  - If any reservation fails, release already-reserved items and cancel order.

This is a saga pattern (without a saga orchestrator for now).
Phase 5 will add a proper outbox pattern / compensating transactions.
"""

import logging
import math
from decimal import Decimal
from typing import Optional

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import (
    InvalidOrderStateError,
    InventoryServiceError,
    OrderNotFoundError,
    StockValidationError,
)
from app.models.order import Order, OrderItem, OrderStatus
from app.schemas.order import CancelOrderRequest, OrderCreate

logger = logging.getLogger(__name__)


class OrderService:
    """All order business operations. One instance per request."""

    def __init__(
        self,
        db: AsyncSession,
        inventory_base_url: str,
        pubsub_publisher=None,
    ) -> None:
        self._db = db
        self._inventory_url = inventory_base_url.rstrip("/")
        self._publisher = pubsub_publisher

    # ── Create ────────────────────────────────────────────────────────────────

    async def create_order(self, data: OrderCreate) -> Order:
        """
        Full order creation saga:
          validate → persist → reserve stock → confirm → publish event.
        """
        # 1. Validate all products exist and have enough stock
        await self._validate_stock(data)

        # 2. Persist Order + items (PENDING)
        total = sum(i.unit_price * i.quantity for i in data.items)
        order = Order(
            customer_id=data.customer_id,
            status=OrderStatus.PENDING.value,
            total_amount=total,
            shipping_address=data.shipping_address,
            warehouse_hint=data.warehouse_hint,
        )
        self._db.add(order)
        await self._db.flush()  # get order.id without committing

        for item_data in data.items:
            item = OrderItem(
                order_id=order.id,
                product_id=item_data.product_id,
                sku=item_data.sku,
                quantity=item_data.quantity,
                unit_price=item_data.unit_price,
            )
            self._db.add(item)

        await self._db.flush()
        await self._db.refresh(order)

        logger.info("Created order id=%d customer=%s", order.id, order.customer_id)

        # 3. Reserve stock for each item — rollback on failure
        reserved: list[tuple[int, int]] = []  # [(product_id, quantity)]
        try:
            for item_data in data.items:
                await self._call_reserve(
                    product_id=item_data.product_id,
                    quantity=item_data.quantity,
                    order_id=str(order.id),
                )
                reserved.append((item_data.product_id, item_data.quantity))
        except Exception as exc:
            logger.error("Stock reservation failed for order id=%d: %s", order.id, exc)
            await self._release_reserved(reserved, str(order.id))
            order.status = OrderStatus.CANCELLED.value
            order.cancellation_reason = "Stock reservation failed"
            await self._db.flush()
            raise

        # 4. Confirm order
        order.status = OrderStatus.CONFIRMED.value
        order.version += 1
        await self._db.flush()

        # 5. Publish order.created event
        self._publish_order_created(order)

        logger.info("Order id=%d confirmed", order.id)
        return order

    # ── Read ──────────────────────────────────────────────────────────────────

    async def get_order(self, order_id: int) -> Order:
        result = await self._db.execute(
            select(Order).where(Order.id == order_id)
        )
        order = result.scalar_one_or_none()
        if order is None:
            raise OrderNotFoundError(order_id)
        return order

    async def list_orders(
        self,
        page: int = 1,
        page_size: int = 20,
        customer_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> tuple[list[Order], int]:
        base = select(Order)
        count_q = select(func.count()).select_from(Order)

        if customer_id:
            base = base.where(Order.customer_id == customer_id)
            count_q = count_q.where(Order.customer_id == customer_id)
        if status:
            base = base.where(Order.status == status)
            count_q = count_q.where(Order.status == status)

        total: int = await self._db.scalar(count_q) or 0
        items_q = (
            base.order_by(Order.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self._db.execute(items_q)
        return list(result.scalars().all()), total

    # ── State transitions ─────────────────────────────────────────────────────

    async def cancel_order(self, order_id: int, req: CancelOrderRequest) -> Order:
        """
        Cancel an order.
        If the order was CONFIRMED, release stock reservations.
        """
        order = await self.get_order(order_id)
        if not order.can_transition_to(OrderStatus.CANCELLED):
            raise InvalidOrderStateError(order_id, order.status, "cancel")

        was_confirmed = order.status == OrderStatus.CONFIRMED.value

        order.status = OrderStatus.CANCELLED.value
        order.cancellation_reason = req.reason
        order.version += 1
        await self._db.flush()

        # Release reserved stock if order was already confirmed
        if was_confirmed:
            reserved = [(item.product_id, item.quantity) for item in order.items]
            await self._release_reserved(reserved, str(order_id))

        logger.info("Cancelled order id=%d reason=%s", order_id, req.reason)
        return order

    async def update_status(self, order_id: int, new_status: OrderStatus) -> Order:
        """
        Internal status update (called by Pub/Sub subscriber when fulfillment
        events arrive).
        """
        order = await self.get_order(order_id)
        if not order.can_transition_to(new_status):
            raise InvalidOrderStateError(order_id, order.status, f"transition to {new_status}")

        order.status = new_status.value
        order.version += 1
        await self._db.flush()
        logger.info("Order id=%d transitioned to %s", order_id, new_status)
        return order

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _validate_stock(self, data: OrderCreate) -> None:
        """Check each product exists and has sufficient on-hand stock."""
        async with httpx.AsyncClient(timeout=5.0) as client:
            for item in data.items:
                try:
                    r = await client.get(
                        f"{self._inventory_url}/api/v1/products/{item.product_id}"
                    )
                    if r.status_code == 404:
                        raise StockValidationError(
                            f"Product {item.product_id} (SKU: {item.sku}) not found in inventory."
                        )
                    r.raise_for_status()
                    product = r.json()
                    if product["quantity_on_hand"] < item.quantity:
                        raise StockValidationError(
                            f"Insufficient stock for SKU '{item.sku}': "
                            f"requested {item.quantity}, available {product['quantity_on_hand']}."
                        )
                except (httpx.TimeoutException, httpx.ConnectError) as exc:
                    raise InventoryServiceError() from exc

    async def _call_reserve(self, product_id: int, quantity: int, order_id: str) -> None:
        async with httpx.AsyncClient(timeout=5.0) as client:
            try:
                r = await client.post(
                    f"{self._inventory_url}/api/v1/products/{product_id}/reserve",
                    json={"quantity": quantity, "order_id": order_id},
                )
                if r.status_code == 409:
                    raise StockValidationError(r.json().get("detail", "Insufficient stock"))
                r.raise_for_status()
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                raise InventoryServiceError() from exc

    async def _release_reserved(
        self, reserved: list[tuple[int, int]], order_id: str
    ) -> None:
        async with httpx.AsyncClient(timeout=5.0) as client:
            for product_id, quantity in reserved:
                try:
                    await client.post(
                        f"{self._inventory_url}/api/v1/products/{product_id}/release",
                        json={"quantity": quantity, "order_id": order_id},
                    )
                except Exception as exc:
                    logger.warning(
                        "Failed to release stock product_id=%d order_id=%s: %s",
                        product_id, order_id, exc,
                    )

    def _publish_order_created(self, order: Order) -> None:
        if not self._publisher:
            return
        try:
            from shared.events.envelope import EventEnvelope
            from shared.events.order_events import ORDER_CREATED
            envelope = EventEnvelope(
                event_type=ORDER_CREATED,
                source="order-service",
                data={
                    "order_id": order.id,
                    "customer_id": order.customer_id,
                    "items": [
                        {
                            "product_id": item.product_id,
                            "sku": item.sku,
                            "quantity": item.quantity,
                            "unit_price": str(item.unit_price),
                        }
                        for item in order.items
                    ],
                    "total_amount": str(order.total_amount),
                    "shipping_address": order.shipping_address,
                    "warehouse_hint": order.warehouse_hint,
                },
            )
            self._publisher(envelope)
        except Exception:
            logger.exception("Failed to publish order.created event order_id=%d", order.id)
