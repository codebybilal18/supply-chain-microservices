"""
Order and OrderItem ORM models.

Design:
  - Order is the aggregate root; OrderItems are children (cascade delete).
  - `status` uses a string enum — stored as VARCHAR so it's readable in the DB
    without needing a lookup table.  Transitions are enforced in the service layer.
  - `total_amount` is stored for audit purposes even though it can be derived
    from items — avoids re-computation on every read and captures the price
    at time of order placement.
  - `version` column for optimistic locking (same pattern as Inventory).
"""

import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class OrderStatus(str, enum.Enum):
    PENDING = "pending"           # created, awaiting stock validation
    CONFIRMED = "confirmed"       # stock reserved, event published
    PROCESSING = "processing"     # fulfillment assigned
    SHIPPED = "shipped"           # carrier picked up
    DELIVERED = "delivered"       # final state
    CANCELLED = "cancelled"       # order cancelled, stock released


# Valid state transitions
ORDER_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.PENDING: {OrderStatus.CONFIRMED, OrderStatus.CANCELLED},
    OrderStatus.CONFIRMED: {OrderStatus.PROCESSING, OrderStatus.CANCELLED},
    OrderStatus.PROCESSING: {OrderStatus.SHIPPED, OrderStatus.DELIVERED, OrderStatus.CANCELLED},
    OrderStatus.SHIPPED: {OrderStatus.DELIVERED},
    OrderStatus.DELIVERED: set(),
    OrderStatus.CANCELLED: set(),
}


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        Index("ix_orders_customer_status", "customer_id", "status"),
        {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=OrderStatus.PENDING.value, index=True
    )
    total_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    shipping_address: Mapped[str] = mapped_column(Text, nullable=False)
    warehouse_hint: Mapped[str | None] = mapped_column(String(100), nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    items: Mapped[list["OrderItem"]] = relationship(
        "OrderItem", back_populates="order", cascade="all, delete-orphan", lazy="selectin"
    )

    def can_transition_to(self, new_status: OrderStatus) -> bool:
        current = OrderStatus(self.status)
        return new_status in ORDER_TRANSITIONS.get(current, set())

    def __repr__(self) -> str:
        return f"<Order id={self.id} customer={self.customer_id} status={self.status}>"


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = (
        {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[int] = mapped_column(Integer, nullable=False)
    sku: Mapped[str] = mapped_column(String(100), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    order: Mapped["Order"] = relationship("Order", back_populates="items")

    @property
    def line_total(self) -> Decimal:
        return self.unit_price * self.quantity

    def __repr__(self) -> str:
        return f"<OrderItem order={self.order_id} sku={self.sku} qty={self.quantity}>"
