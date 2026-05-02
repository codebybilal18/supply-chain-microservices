"""Pydantic schemas for Fulfillment Service."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class FulfillmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_id: int
    customer_id: str
    status: str
    warehouse_id: Optional[str] = None
    carrier: Optional[str] = None
    tracking_number: Optional[str] = None
    shipping_address: Optional[str] = None
    failure_reason: Optional[str] = None
    version: int
    created_at: datetime
    updated_at: datetime


class FulfillmentListResponse(BaseModel):
    items: list[FulfillmentResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class AdvanceFulfillmentRequest(BaseModel):
    """Manually advance fulfillment to the next state (for testing/ops)."""
    notes: Optional[str] = None


class AssignWarehouseRequest(BaseModel):
    warehouse_id: str
    carrier: str = "standard"


class MarkShippedRequest(BaseModel):
    tracking_number: str
    carrier: Optional[str] = None
