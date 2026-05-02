"""
Pydantic schemas for the Order resource.
"""

from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.models.order import OrderStatus


# ── Item schemas ──────────────────────────────────────────────────────────────

class OrderItemCreate(BaseModel):
    product_id: Annotated[int, Field(gt=0)]
    sku: Annotated[str, Field(min_length=1, max_length=100)]
    quantity: Annotated[int, Field(gt=0)]
    unit_price: Annotated[Decimal, Field(gt=Decimal("0"), decimal_places=2)]


class OrderItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    sku: str
    quantity: int
    unit_price: Decimal
    line_total: Decimal


# ── Order schemas ─────────────────────────────────────────────────────────────

class OrderCreate(BaseModel):
    customer_id: Annotated[str, Field(min_length=1, max_length=100)]
    shipping_address: Annotated[str, Field(min_length=5, max_length=500)]
    warehouse_hint: str | None = None
    items: Annotated[list[OrderItemCreate], Field(min_length=1)]


class OrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: str
    status: str
    total_amount: Decimal
    shipping_address: str
    warehouse_hint: str | None
    cancellation_reason: str | None
    version: int
    items: list[OrderItemResponse]
    created_at: datetime
    updated_at: datetime


class OrderListResponse(BaseModel):
    items: list[OrderResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class OrderStatusUpdate(BaseModel):
    status: OrderStatus
    reason: str | None = None


class CancelOrderRequest(BaseModel):
    reason: Annotated[str, Field(min_length=1, max_length=500)] = "Cancelled by customer"
