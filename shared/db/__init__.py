"""Shared database utilities."""
from shared.db.idempotency import ProcessedEvent, is_already_processed, mark_processed

__all__ = ["ProcessedEvent", "is_already_processed", "mark_processed"]
