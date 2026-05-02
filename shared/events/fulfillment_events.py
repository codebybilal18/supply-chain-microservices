"""
Fulfillment-domain event schemas.
"""

from pydantic import BaseModel


FULFILLMENT_ASSIGNED = "fulfillment.assigned"
FULFILLMENT_COMPLETED = "fulfillment.completed"
FULFILLMENT_FAILED = "fulfillment.failed"


class FulfillmentAssignedData(BaseModel):
    fulfillment_id: int
    order_id: int
    warehouse_id: str
    carrier: str
    estimated_delivery_days: int


class FulfillmentCompletedData(BaseModel):
    fulfillment_id: int
    order_id: int
    tracking_number: str
    carrier: str


class FulfillmentFailedData(BaseModel):
    fulfillment_id: int
    order_id: int
    reason: str
