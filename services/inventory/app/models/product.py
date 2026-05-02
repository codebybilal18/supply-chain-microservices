"""
Product ORM model.

Design decisions:
  - `version` column implements optimistic locking — incremented on every
    write so concurrent updates to the same row can be detected (Phase 2
    will use this with SELECT ... FOR UPDATE for reservation flows).
  - `quantity_reserved` tracks units committed to in-flight orders but not
    yet deducted from physical stock.
  - `quantity_on_hand` is a Python property (not a DB column) to avoid
    denormalisation: available − reserved is always computed fresh.
  - `reorder_point` enables low-stock alerting (Pub/Sub event in Phase 2).
  - All timestamps use MySQL `server_default` so the DB is the source of
    truth even if records are inserted outside the application.
  - `charset=utf8mb4` is set at the table level to handle emoji/Arabic SKUs.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        # Composite index for category + SKU lookups (common filter pattern)
        Index("ix_products_category_sku", "category", "sku"),
        {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    # ── Primary key ───────────────────────────────────────────────────────────
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # ── Business fields ───────────────────────────────────────────────────────
    sku: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True,
        comment="Stock-Keeping Unit — unique external identifier",
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True,
        comment="Product category used for filtering and routing",
    )
    unit_price: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False,
        comment="Price in base currency (AED for noon)",
    )

    # ── Stock counters ────────────────────────────────────────────────────────
    quantity_available: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
        comment="Total units physically in warehouse",
    )
    quantity_reserved: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
        comment="Units locked for in-flight orders (not yet shipped)",
    )
    reorder_point: Mapped[int] = mapped_column(
        Integer, nullable=False, default=10,
        comment="Trigger low-stock Pub/Sub event when on_hand falls below this",
    )

    # ── Concurrency control ───────────────────────────────────────────────────
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1,
        comment="Optimistic-lock version counter; increment on every write",
    )

    # ── Audit timestamps ──────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # ── Computed helpers ──────────────────────────────────────────────────────
    @property
    def quantity_on_hand(self) -> int:
        """Units actually available to reserve (available − reserved)."""
        return self.quantity_available - self.quantity_reserved

    @property
    def is_low_stock(self) -> bool:
        """True when on-hand stock drops to or below the reorder point."""
        return self.quantity_on_hand <= self.reorder_point

    def __repr__(self) -> str:
        return (
            f"<Product id={self.id} sku={self.sku!r} "
            f"on_hand={self.quantity_on_hand}>"
        )
