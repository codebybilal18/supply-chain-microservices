"""ORM models package — import all models here so Alembic autogenerate sees them."""

from app.models.product import Product  # noqa: F401

__all__ = ["Product"]
