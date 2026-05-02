"""
Add query-optimisation indexes.

Phase 4: performance improvements for common access patterns:
  - (customer_id, created_at): paginate a customer's order history
  - (status, created_at):      filter-by-status + time-ordered listing
  - (order_id, sku):           composite on order_items for fulfilment lookups

Revision ID: 0002_add_indexes
Revises: 0001
Create Date: 2026-05-03
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0002_add_indexes"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Composite: customer order history (most recent first)
    op.create_index(
        "ix_orders_customer_created",
        "orders",
        ["customer_id", "created_at"],
    )
    # Composite: status dashboard — filter by status, sorted by time
    op.create_index(
        "ix_orders_status_created",
        "orders",
        ["status", "created_at"],
    )
    # order_items: look up items by SKU across orders (stock analysis)
    op.create_index(
        "ix_order_items_sku",
        "order_items",
        ["sku"],
    )
    # order_items: composite for fetching items of an order by product
    op.create_index(
        "ix_order_items_order_product",
        "order_items",
        ["order_id", "product_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_order_items_order_product", table_name="order_items")
    op.drop_index("ix_order_items_sku", table_name="order_items")
    op.drop_index("ix_orders_status_created", table_name="orders")
    op.drop_index("ix_orders_customer_created", table_name="orders")
