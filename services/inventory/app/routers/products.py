"""
Product CRUD and stock-management endpoints.

URL convention: /api/v1/products[/{product_id}][/reserve|/release]

Route summary:
  GET    /api/v1/products               — paginated list with filters
  POST   /api/v1/products               — create a product
  GET    /api/v1/products/{id}          — get one product by ID
  PUT    /api/v1/products/{id}          — partial update
  DELETE /api/v1/products/{id}          — hard delete
  POST   /api/v1/products/{id}/reserve  — reserve stock for an order
  POST   /api/v1/products/{id}/release  — release previously reserved stock
"""

import math
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_cache, get_db
from app.schemas.product import (
    ProductCreate,
    ProductListResponse,
    ProductResponse,
    ProductUpdate,
    StockOperationRequest,
    StockOperationResponse,
)
from app.services.inventory_service import InventoryService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/products", tags=["products"])


# ── Helper ────────────────────────────────────────────────────────────────────

def _make_service(
    db: AsyncSession = Depends(get_db),
    cache=Depends(get_cache),
) -> InventoryService:
    return InventoryService(db, cache=cache)


# ── List ──────────────────────────────────────────────────────────────────────

@router.get(
    "",
    response_model=ProductListResponse,
    summary="List products",
)
async def list_products(
    page: int = Query(default=1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    category: Optional[str] = Query(default=None, description="Filter by category"),
    low_stock_only: bool = Query(default=False, description="Return only low-stock items"),
    service: InventoryService = Depends(_make_service),
) -> ProductListResponse:
    items, total = await service.list_products(
        page=page,
        page_size=page_size,
        category=category,
        low_stock_only=low_stock_only,
    )
    total_pages = max(1, math.ceil(total / page_size))
    return ProductListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


# ── Create ────────────────────────────────────────────────────────────────────

@router.post(
    "",
    response_model=ProductResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a product",
)
async def create_product(
    data: ProductCreate,
    service: InventoryService = Depends(_make_service),
) -> ProductResponse:
    return await service.create_product(data)


# ── Read one ──────────────────────────────────────────────────────────────────

@router.get(
    "/{product_id}",
    response_model=ProductResponse,
    summary="Get a product by ID",
)
async def get_product(
    product_id: int,
    service: InventoryService = Depends(_make_service),
) -> ProductResponse:
    return await service.get_product(product_id)


# ── Update ────────────────────────────────────────────────────────────────────

@router.put(
    "/{product_id}",
    response_model=ProductResponse,
    summary="Update a product (partial)",
)
async def update_product(
    product_id: int,
    data: ProductUpdate,
    service: InventoryService = Depends(_make_service),
) -> ProductResponse:
    return await service.update_product(product_id, data)


# ── Delete ────────────────────────────────────────────────────────────────────

@router.delete(
    "/{product_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a product",
)
async def delete_product(
    product_id: int,
    service: InventoryService = Depends(_make_service),
) -> None:
    await service.delete_product(product_id)


# ── Stock operations ──────────────────────────────────────────────────────────

@router.post(
    "/{product_id}/reserve",
    response_model=StockOperationResponse,
    summary="Reserve stock for an order",
    description=(
        "Lock `quantity` units of a product for an in-flight order. "
        "Uses a row-level lock to prevent concurrent over-reservation. "
        "Returns 409 if available stock is insufficient."
    ),
)
async def reserve_stock(
    product_id: int,
    data: StockOperationRequest,
    service: InventoryService = Depends(_make_service),
) -> StockOperationResponse:
    product = await service.reserve_stock(product_id, data.quantity, data.order_id)
    return StockOperationResponse(
        product_id=product.id,
        sku=product.sku,
        quantity_delta=data.quantity,
        quantity_reserved=product.quantity_reserved,
        quantity_on_hand=product.quantity_on_hand,
        order_id=data.order_id,
        is_low_stock=product.is_low_stock,
    )


@router.post(
    "/{product_id}/release",
    response_model=StockOperationResponse,
    summary="Release previously reserved stock",
    description=(
        "Undo a prior reservation — used when an order is cancelled or fails. "
        "Returns 409 if releasing more units than are currently reserved."
    ),
)
async def release_stock(
    product_id: int,
    data: StockOperationRequest,
    service: InventoryService = Depends(_make_service),
) -> StockOperationResponse:
    product = await service.release_stock(product_id, data.quantity, data.order_id)
    return StockOperationResponse(
        product_id=product.id,
        sku=product.sku,
        quantity_delta=-data.quantity,
        quantity_reserved=product.quantity_reserved,
        quantity_on_hand=product.quantity_on_hand,
        order_id=data.order_id,
        is_low_stock=product.is_low_stock,
    )
