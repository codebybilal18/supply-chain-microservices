"""
Add query-optimisation indexes.

Phase 4: performance improvements for common access patterns:
  - (status, created_at):         filter-by-status + time-ordered listing
  - (customer_id, status):        customer fulfilment history by status
  - (carrier, status):            carrier-level SLA reporting
  - (created_at):                 chronological audit / admin listing

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
    # Status dashboard — most recent first
    op.create_index(
        "ix_fulfillments_status_created",
        "fulfillments",
        ["status", "created_at"],
    )
    # Customer fulfilment history (e.g. track my shipments)
    op.create_index(
        "ix_fulfillments_customer_status",
        "fulfillments",
        ["customer_id", "status"],
    )
    # Carrier SLA reporting (aggregate shipped/completed per carrier)
    op.create_index(
        "ix_fulfillments_carrier_status",
        "fulfillments",
        ["carrier", "status"],
    )
    # Chronological audit listing
    op.create_index(
        "ix_fulfillments_created_at",
        "fulfillments",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_fulfillments_created_at", table_name="fulfillments")
    op.drop_index("ix_fulfillments_carrier_status", table_name="fulfillments")
    op.drop_index("ix_fulfillments_customer_status", table_name="fulfillments")
    op.drop_index("ix_fulfillments_status_created", table_name="fulfillments")
