"""
Cloud Pub/Sub publisher.

Design:
  - Uses google-cloud-pubsub's PublisherClient.
  - When PUBSUB_EMULATOR_HOST is set, the client automatically points to
    the local emulator (no real GCP credentials required for local dev).
  - `publish_event` is synchronous (wraps the future.result()) because
    FastAPI route handlers call it inside an async context — the network
    round-trip is fast enough that blocking is acceptable here.
    Phase 5 can upgrade this to a background task if needed.
  - The publisher is a module-level singleton to reuse the gRPC channel.

Usage:
    from shared.pubsub.publisher import publish_event
    from shared.events.envelope import EventEnvelope
    from shared.events.order_events import ORDER_CREATED, OrderCreatedData

    envelope = EventEnvelope(
        event_type=ORDER_CREATED,
        source="order-service",
        data=OrderCreatedData(...).model_dump(),
    )
    publish_event("order-events", envelope)
"""

import logging
import os
from typing import TYPE_CHECKING

from shared.events.envelope import EventEnvelope

if TYPE_CHECKING:
    from google.cloud.pubsub_v1 import PublisherClient

logger = logging.getLogger(__name__)

_publisher: "PublisherClient | None" = None


def _get_publisher() -> "PublisherClient":
    global _publisher
    if _publisher is None:
        from google.cloud import pubsub_v1  # lazy import — not needed in tests

        _publisher = pubsub_v1.PublisherClient()
    return _publisher


def publish_event(topic_id: str, envelope: EventEnvelope, project_id: str) -> str:
    """
    Publish an EventEnvelope to a Pub/Sub topic.

    Args:
        topic_id:   Short topic name (e.g. "order-events").
        envelope:   The event envelope to publish.
        project_id: GCP project ID.

    Returns:
        The published message ID.

    Raises:
        Exception: propagates Pub/Sub client errors to the caller.
    """
    publisher = _get_publisher()
    topic_path = publisher.topic_path(project_id, topic_id)
    data = envelope.to_json_bytes()

    # Pub/Sub attributes for server-side filtering (optional)
    attributes = {
        "event_type": envelope.event_type,
        "source": envelope.source,
        "version": envelope.version,
    }

    future = publisher.publish(topic_path, data, **attributes)
    message_id: str = future.result(timeout=10)
    logger.info(
        "Published event event_type=%s message_id=%s topic=%s",
        envelope.event_type, message_id, topic_id,
    )
    return message_id
