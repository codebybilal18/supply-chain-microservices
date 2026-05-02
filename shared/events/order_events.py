"""
Order-domain event schemas.

Each class represents the `data` payload inside the EventEnvelope for
a specific event type.  Keeping schemas in the shared library means
producers and consumers share the same validated types.
"""

from decimal import Decimal
from pydantic import BaseModel


# ── Event type constants ───────────────────────────────────────────────────────
ORDER_CREATED = "order.created"
ORDER_CANCELLED = "order.cancelled"
ORDER_COMPLETED = "order.completed"


class OrderItemData(BaseModel):
    product_id: int
    sku: str
    quantity: int
    unit_price: Decimal


class OrderCreatedData(BaseModel):
    order_id: int
    customer_id: str
    items: list[OrderItemData]
    total_amount: Decimal
    shipping_address: str
    warehouse_hint: str | None = None


class OrderCancelledData(BaseModel):
    order_id: int
    reason: str


class OrderCompletedData(BaseModel):
    order_id: int
    fulfillment_id: int
