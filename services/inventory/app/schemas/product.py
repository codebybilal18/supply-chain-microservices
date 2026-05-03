"""
Pydantic schemas for the Product resource.

Separation of concerns:
  - ProductCreate   — POST /products  request body (no id/timestamps)
  - ProductUpdate   — PUT  /products/{id} (all fields optional — partial update)
  - ProductResponse — all GET / POST / PUT responses (includes computed fields)
  - ProductListResponse — paginated list wrapper
  - StockOperationRequest  — body for /reserve and /release
  - StockOperationResponse — result of a stock operation
"""

from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


# ── Shared base ───────────────────────────────────────────────────────────────

class ProductBase(BaseModel):
    sku: Annotated[str, Field(min_length=1, max_length=100, examples=["CAT-ELEC-001"])]
    name: Annotated[str, Field(min_length=1, max_length=255, examples=["Samsung 65\" QLED TV"])]
    description: str | None = Field(default=None, max_length=2000)
    category: Annotated[str, Field(min_length=1, max_length=100, examples=["electronics"])]
    unit_price: Annotated[
        Decimal,
        Field(gt=Decimal("0"), decimal_places=2, examples=[Decimal("1999.99")]),
    ]
    quantity_available: Annotated[int, Field(ge=0, examples=[50])]
    reorder_point: Annotated[int, Field(ge=0, default=10, examples=[10])]


# ── Request schemas ───────────────────────────────────────────────────────────

class ProductCreate(ProductBase):
    """Request body for creating a new product."""
    pass


class ProductUpdate(BaseModel):
    """
    Request body for updating a product.
    All fields are optional — only supplied fields are modified (PATCH semantics
    despite using PUT, which is idiomatic for resource-level updates here).
    """
    name: Annotated[str, Field(min_length=1, max_length=255)] | None = None
    description: str | None = None
    category: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    unit_price: Annotated[Decimal, Field(gt=Decimal("0"), decimal_places=2)] | None = None
    quantity_available: Annotated[int, Field(ge=0)] | None = None
    reorder_point: Annotated[int, Field(ge=0)] | None = None


# ── Response schemas ──────────────────────────────────────────────────────────

class ProductResponse(ProductBase):
    """Full product representation returned by the API."""

    model_config = ConfigDict(from_attributes=True)  # read from ORM objects

    id: int
    quantity_reserved: int
    quantity_on_hand: int   # computed property on the ORM model
    is_low_stock: bool      # computed property on the ORM model
    version: int
    created_at: datetime
    updated_at: datetime


class ProductListResponse(BaseModel):
    """Paginated list of products."""

    items: list[ProductResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


# ── Stock operation schemas ───────────────────────────────────────────────────

class StockOperationRequest(BaseModel):
    """Body for /reserve and /release endpoints."""

    quantity: Annotated[int, Field(gt=0, examples=[5])]
    order_id: Annotated[
        str,
        Field(min_length=1, max_length=100, examples=["ORD-20260503-0001"]),
    ]


class StockOperationResponse(BaseModel):
    """Result of a reserve or release operation."""

    product_id: int
    sku: str
    quantity_delta: int          # positive = reserved, negative = released
    quantity_reserved: int       # new total reserved count
    quantity_on_hand: int        # new on-hand count
    order_id: str
    is_low_stock: bool
