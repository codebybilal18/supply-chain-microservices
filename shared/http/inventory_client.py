"""
Typed async HTTP client for calling the Inventory Service.

The Order Service uses this to validate stock before creating an order.
Using httpx.AsyncClient keeps the call non-blocking on FastAPI's event loop.

The base URL is injected via environment variable so it points to:
  - Docker Compose: http://inventory:8000
  - GCP Cloud Run:  https://inventory-<hash>-uc.a.run.app
"""

import logging
from decimal import Decimal

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 5.0  # seconds


class ProductStockResponse(BaseModel):
    id: int
    sku: str
    quantity_on_hand: int
    quantity_reserved: int
    is_low_stock: bool


class StockReserveResponse(BaseModel):
    product_id: int
    sku: str
    quantity_delta: int
    quantity_reserved: int
    quantity_on_hand: int
    order_id: str
    is_low_stock: bool


class InventoryClient:
    """Async HTTP client for the Inventory Service."""

    def __init__(self, base_url: str, timeout: float = DEFAULT_TIMEOUT) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    async def get_product(self, product_id: int) -> ProductStockResponse:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.get(f"{self._base_url}/api/v1/products/{product_id}")
            r.raise_for_status()
            return ProductStockResponse(**r.json())

    async def reserve_stock(
        self, product_id: int, quantity: int, order_id: str
    ) -> StockReserveResponse:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.post(
                f"{self._base_url}/api/v1/products/{product_id}/reserve",
                json={"quantity": quantity, "order_id": order_id},
            )
            r.raise_for_status()
            return StockReserveResponse(**r.json())

    async def release_stock(
        self, product_id: int, quantity: int, order_id: str
    ) -> StockReserveResponse:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.post(
                f"{self._base_url}/api/v1/products/{product_id}/release",
                json={"quantity": quantity, "order_id": order_id},
            )
            r.raise_for_status()
            return StockReserveResponse(**r.json())
