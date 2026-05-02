"""
Cloud Pub/Sub pull subscriber base class.

Design:
  - Uses a blocking `pull` loop in a separate thread so it does not
    interfere with FastAPI's asyncio event loop.
  - Ack deadline: 30 s (message re-delivered if processing exceeds this).
  - On unhandled exception the message is NOT acked — it will be
    re-delivered up to the subscription's max retry count.
  - `dead_letter_topic` support is configured in the GCP subscription
    (not in code), so failed messages eventually go to a DLQ topic.

Usage:
    class OrderCreatedSubscriber(PullSubscriber):
        subscription_id = "inventory-order-created-sub"

        def handle(self, envelope: EventEnvelope) -> None:
            data = OrderCreatedData(**envelope.data)
            # ... process ...

    sub = OrderCreatedSubscriber(project_id="my-project")
    sub.start()   # runs in background thread
"""

import logging
import threading
from abc import ABC, abstractmethod
from typing import Callable

from shared.events.envelope import EventEnvelope

logger = logging.getLogger(__name__)


class PullSubscriber(ABC):
    """Base class for synchronous pull-based Pub/Sub subscribers."""

    subscription_id: str  # must be overridden in subclasses

    def __init__(self, project_id: str, max_messages: int = 10) -> None:
        self._project_id = project_id
        self._max_messages = max_messages
        self._running = False
        self._thread: threading.Thread | None = None

    @abstractmethod
    def handle(self, envelope: EventEnvelope) -> None:
        """Process a single event. Raise to NACK (message will be redelivered)."""

    def start(self) -> None:
        """Start consuming in a daemon background thread."""
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("Subscriber started subscription=%s", self.subscription_id)

    def stop(self) -> None:
        self._running = False
        logger.info("Subscriber stopping subscription=%s", self.subscription_id)

    def _run_loop(self) -> None:
        from google.cloud import pubsub_v1

        subscriber = pubsub_v1.SubscriberClient()
        sub_path = subscriber.subscription_path(self._project_id, self.subscription_id)

        with subscriber:
            while self._running:
                try:
                    response = subscriber.pull(
                        request={
                            "subscription": sub_path,
                            "max_messages": self._max_messages,
                        },
                        timeout=5,
                    )
                except Exception as exc:
                    logger.warning("Pull error subscription=%s: %s", self.subscription_id, exc)
                    continue

                ack_ids = []
                for msg in response.received_messages:
                    try:
                        envelope = EventEnvelope.from_json_bytes(msg.message.data)
                        self.handle(envelope)
                        ack_ids.append(msg.ack_id)
                    except Exception:
                        logger.exception(
                            "Handler error subscription=%s event_type=%s — NACK",
                            self.subscription_id,
                            msg.message.attributes.get("event_type", "unknown"),
                        )

                if ack_ids:
                    subscriber.acknowledge(
                        request={"subscription": sub_path, "ack_ids": ack_ids}
                    )
