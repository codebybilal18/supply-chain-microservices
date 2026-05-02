"""
Inventory-domain event schemas.
"""

from pydantic import BaseModel


STOCK_RESERVED = "inventory.stock_reserved"
STOCK_RELEASED = "inventory.stock_released"
LOW_STOCK = "inventory.low_stock"


class StockReservedData(BaseModel):
    order_id: int
    reservations: list[dict]   # [{product_id, sku, quantity}]


class StockReleasedData(BaseModel):
    order_id: int
    releases: list[dict]


class LowStockData(BaseModel):
    product_id: int
    sku: str
    quantity_on_hand: int
    reorder_point: int
