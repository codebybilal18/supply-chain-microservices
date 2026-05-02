"""
Fulfillment ORM model.

FulfillmentStatus lifecycle:
  PENDING → ASSIGNED (warehouse selected)
  ASSIGNED → PICKING (warehouse worker picks items)
  PICKING → SHIPPED (carrier picked up)
  SHIPPED → COMPLETED (delivered to customer)
  Any state → FAILED (unrecoverable error)
"""

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class FulfillmentStatus(str, enum.Enum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    PICKING = "picking"
    SHIPPED = "shipped"
    COMPLETED = "completed"
    FAILED = "failed"


FULFILLMENT_TRANSITIONS: dict[FulfillmentStatus, set[FulfillmentStatus]] = {
    FulfillmentStatus.PENDING: {FulfillmentStatus.ASSIGNED, FulfillmentStatus.FAILED},
    FulfillmentStatus.ASSIGNED: {FulfillmentStatus.PICKING, FulfillmentStatus.FAILED},
    FulfillmentStatus.PICKING: {FulfillmentStatus.SHIPPED, FulfillmentStatus.FAILED},
    FulfillmentStatus.SHIPPED: {FulfillmentStatus.COMPLETED, FulfillmentStatus.FAILED},
    FulfillmentStatus.COMPLETED: set(),
    FulfillmentStatus.FAILED: set(),
}


class Fulfillment(Base):
    __tablename__ = "fulfillments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True, unique=True)
    customer_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=FulfillmentStatus.PENDING.value, index=True
    )
    warehouse_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    carrier: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    tracking_number: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    shipping_address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    failure_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    def can_transition_to(self, new_status: FulfillmentStatus) -> bool:
        current = FulfillmentStatus(self.status)
        return new_status in FULFILLMENT_TRANSITIONS.get(current, set())
