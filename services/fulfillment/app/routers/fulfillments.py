"""
Fulfillment CRUD and lifecycle endpoints.

Routes:
  GET    /api/v1/fulfillments                  — list fulfillments (paginated)
  GET    /api/v1/fulfillments/{id}             — get by fulfillment ID
  GET    /api/v1/fulfillments/by-order/{id}    — get by order ID
  POST   /api/v1/fulfillments/{id}/pick        — start picking
  POST   /api/v1/fulfillments/{id}/ship        — mark shipped
  POST   /api/v1/fulfillments/{id}/complete    — mark completed
  POST   /api/v1/fulfillments/{id}/fail        — mark failed
"""

import math
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query, status, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.schemas.fulfillment import (
    FulfillmentListResponse,
    FulfillmentResponse,
    MarkShippedRequest,
)
from app.services.fulfillment_service import FulfillmentService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/fulfillments", tags=["fulfillments"])


def _make_service(request: Request, db: AsyncSession = Depends(get_db)) -> FulfillmentService:
    publisher = getattr(request.app.state, "pubsub_publisher", None)
    return FulfillmentService(db=db, pubsub_publisher=publisher)


@router.get("", response_model=FulfillmentListResponse, summary="List fulfillments")
async def list_fulfillments(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    service: FulfillmentService = Depends(_make_service),
) -> FulfillmentListResponse:
    items, total = await service.list_fulfillments(page=page, page_size=page_size, status=status_filter)
    return FulfillmentListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=max(1, math.ceil(total / page_size)),
    )


@router.get("/by-order/{order_id}", response_model=FulfillmentResponse, summary="Get fulfillment by order ID")
async def get_by_order(
    order_id: int,
    service: FulfillmentService = Depends(_make_service),
) -> FulfillmentResponse:
    return await service.get_by_order(order_id)


@router.get("/{fulfillment_id}", response_model=FulfillmentResponse, summary="Get fulfillment by ID")
async def get_fulfillment(
    fulfillment_id: int,
    service: FulfillmentService = Depends(_make_service),
) -> FulfillmentResponse:
    return await service.get_fulfillment(fulfillment_id)


@router.post("/{fulfillment_id}/pick", response_model=FulfillmentResponse, summary="Start picking")
async def start_picking(
    fulfillment_id: int,
    service: FulfillmentService = Depends(_make_service),
) -> FulfillmentResponse:
    return await service.start_picking(fulfillment_id)


@router.post("/{fulfillment_id}/ship", response_model=FulfillmentResponse, summary="Mark shipped")
async def mark_shipped(
    fulfillment_id: int,
    req: MarkShippedRequest,
    service: FulfillmentService = Depends(_make_service),
) -> FulfillmentResponse:
    return await service.mark_shipped(fulfillment_id, req)


@router.post("/{fulfillment_id}/complete", response_model=FulfillmentResponse, summary="Mark completed")
async def mark_completed(
    fulfillment_id: int,
    service: FulfillmentService = Depends(_make_service),
) -> FulfillmentResponse:
    return await service.mark_completed(fulfillment_id)


@router.post(
    "/{fulfillment_id}/fail",
    response_model=FulfillmentResponse,
    status_code=status.HTTP_200_OK,
    summary="Mark failed",
)
async def mark_failed(
    fulfillment_id: int,
    reason: str = Query(..., description="Failure reason"),
    service: FulfillmentService = Depends(_make_service),
) -> FulfillmentResponse:
    return await service.mark_failed(fulfillment_id, reason)
