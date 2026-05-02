"""
Canonical event envelope.

Every Pub/Sub message across all services is wrapped in this envelope.
Design:
  - `event_id`   — UUID generated at publish time; used for idempotency checks.
  - `event_type` — dot-separated namespaced string (e.g. "order.created").
  - `source`     — originating service name for traceability.
  - `version`    — schema version; consumers can reject unknown versions.
  - `timestamp`  — ISO-8601 UTC; the producing service sets this.
  - `data`       — arbitrary dict payload; each event type defines its own schema.
  - `correlation_id` — propagated from the inbound HTTP request for distributed tracing.
"""

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class EventEnvelope(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str
    source: str
    version: str = "1.0"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    correlation_id: str | None = None
    data: dict[str, Any]

    def to_json_bytes(self) -> bytes:
        """Serialise to UTF-8 JSON bytes for Pub/Sub message data field."""
        return self.model_dump_json().encode("utf-8")

    @classmethod
    def from_json_bytes(cls, raw: bytes) -> "EventEnvelope":
        return cls.model_validate_json(raw)
