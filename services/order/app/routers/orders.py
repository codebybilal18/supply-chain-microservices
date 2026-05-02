"""
Order CRUD and lifecycle endpoints.

Routes:
  GET    /api/v1/orders              — list orders (paginated + filterable)
  POST   /api/v1/orders              — create order (validate → reserve → confirm)
  GET    /api/v1/orders/{id}         — get order by ID
  POST   /api/v1/orders/{id}/cancel  — cancel order (releases stock if confirmed)
"""

import math
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query, status, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dependencies import get_db
from app.schemas.order import (
    CancelOrderRequest,
    OrderCreate,
    OrderListResponse,
    OrderResponse,
)
from app.services.order_service import OrderService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/orders", tags=["orders"])


def _make_service(request: Request, db: AsyncSession = Depends(get_db)) -> OrderService:
    publisher = getattr(request.app.state, "pubsub_publisher", None)
    return OrderService(
        db=db,
        inventory_base_url=settings.INVENTORY_SERVICE_URL,
        pubsub_publisher=publisher,
    )


@router.get("", response_model=OrderListResponse, summary="List orders")
async def list_orders(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    customer_id: Optional[str] = Query(default=None),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    service: OrderService = Depends(_make_service),
) -> OrderListResponse:
    items, total = await service.list_orders(
        page=page, page_size=page_size, customer_id=customer_id, status=status_filter
    )
    return OrderListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=max(1, math.ceil(total / page_size)),
    )


@router.post(
    "",
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an order",
)
async def create_order(
    data: OrderCreate,
    service: OrderService = Depends(_make_service),
) -> OrderResponse:
    return await service.create_order(data)


@router.get("/{order_id}", response_model=OrderResponse, summary="Get order by ID")
async def get_order(
    order_id: int,
    service: OrderService = Depends(_make_service),
) -> OrderResponse:
    return await service.get_order(order_id)


@router.post(
    "/{order_id}/cancel",
    response_model=OrderResponse,
    summary="Cancel an order",
)
async def cancel_order(
    order_id: int,
    data: CancelOrderRequest,
    service: OrderService = Depends(_make_service),
) -> OrderResponse:
    return await service.cancel_order(order_id, data)
