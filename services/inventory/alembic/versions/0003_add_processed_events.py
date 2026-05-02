"""Add processed_events table for idempotent event processing.

Revision ID: 0003_add_processed_events
Revises: 0002_add_indexes
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0003_add_processed_events"
down_revision: str = "0002_add_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "processed_events",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column(
            "service_name",
            sa.String(100),
            nullable=False,
            comment="Service that processed the event",
        ),
        sa.Column(
            "event_id",
            sa.String(36),
            nullable=False,
            comment="UUID from EventEnvelope.event_id",
        ),
        sa.Column(
            "processed_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "service_name", "event_id", name="uq_processed_events"
        ),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index(
        "ix_processed_events_processed_at",
        "processed_events",
        ["processed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_processed_events_processed_at", table_name="processed_events")
    op.drop_table("processed_events")
