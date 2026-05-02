"""
Add query-optimisation indexes.

Phase 4: performance improvements for common access patterns:
  - (category, quantity_available): low-stock filtered list by category
  - (quantity_available, reorder_point): global low-stock check
  - (created_at): time-ordered product listing (admin views)

Revision ID: 0002_add_indexes
Revises: 0001_initial
Create Date: 2026-05-03
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_add_indexes"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Composite index: category filter + low-stock threshold
    op.create_index(
        "ix_products_category_qty",
        "products",
        ["category", "quantity_available"],
    )
    # Composite index: quantity_available vs reorder_point (low-stock detection)
    op.create_index(
        "ix_products_qty_reorder",
        "products",
        ["quantity_available", "reorder_point"],
    )
    # Chronological listing (admin / audit queries)
    op.create_index(
        "ix_products_created_at",
        "products",
        ["created_at"],
    )
    # Covering index for stock reservation queries (SELECT FOR UPDATE path)
    op.create_index(
        "ix_products_sku_qty",
        "products",
        ["sku", "quantity_available", "quantity_reserved"],
    )


def downgrade() -> None:
    op.drop_index("ix_products_sku_qty", table_name="products")
    op.drop_index("ix_products_created_at", table_name="products")
    op.drop_index("ix_products_qty_reorder", table_name="products")
    op.drop_index("ix_products_category_qty", table_name="products")
