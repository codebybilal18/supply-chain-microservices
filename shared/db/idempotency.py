"""
Shared idempotency helper for Pub/Sub event subscribers.

Usage in a subscriber:

    from shared.db.idempotency import is_already_processed, mark_processed

    async with AsyncSessionLocal() as session:
        if await is_already_processed(session, "inventory-service", event_id):
            return  # skip duplicate
        # ... process the event ...
        await mark_processed(session, "inventory-service", event_id)
        await session.commit()

The `processed_events` table is created by each service's Alembic migration
`0003_add_processed_events.py`.

Design:
  - (service_name, event_id) UNIQUE — guarantees exactly-once processing
    even under concurrent message delivery.
  - Rows are retained indefinitely for audit purposes.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

__all__ = ["ProcessedEvent", "is_already_processed", "mark_processed"]


class _Base(DeclarativeBase):
    """Isolated declarative base — does not share metadata with service models."""
    pass


class ProcessedEvent(_Base):
    """Records which Pub/Sub events have been successfully processed."""

    __tablename__ = "processed_events"
    __table_args__ = (
        UniqueConstraint("service_name", "event_id", name="uq_processed_events"),
        {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    service_name: Mapped[str] = mapped_column(
        String(100), nullable=False,
        comment="Service that processed the event",
    )
    event_id: Mapped[str] = mapped_column(
        String(36), nullable=False,
        comment="UUID from EventEnvelope.event_id",
    )
    processed_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False,
    )


async def is_already_processed(
    session: AsyncSession, service_name: str, event_id: str
) -> bool:
    """Return True if this (service_name, event_id) was already committed."""
    from sqlalchemy import select

    row = await session.scalar(
        select(ProcessedEvent.id).where(
            ProcessedEvent.service_name == service_name,
            ProcessedEvent.event_id == event_id,
        )
    )
    return row is not None


async def mark_processed(
    session: AsyncSession, service_name: str, event_id: str
) -> None:
    """Insert a ProcessedEvent record.  Must be followed by session.commit()."""
    session.add(
        ProcessedEvent(service_name=service_name, event_id=event_id)
    )
