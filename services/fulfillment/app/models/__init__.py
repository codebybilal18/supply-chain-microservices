"""Models package — export Base for Alembic."""
from app.database import Base
from app.models.fulfillment import Fulfillment  # noqa: F401 — register with metadata

__all__ = ["Base", "Fulfillment"]
