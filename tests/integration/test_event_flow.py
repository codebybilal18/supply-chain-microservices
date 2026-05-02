"""
Integration tests — Event-Driven Order Flow

These tests verify the end-to-end Pub/Sub event flow between services using a
live Pub/Sub emulator.  They do NOT start the FastAPI services; instead they
simulate publishing events and assert what lands on relevant topics/subscriptions.

Test topology
─────────────
    [test] ──publish──> order-events
                             │
         ┌───────────────────┤
         │                   │
    inventory-order-         fulfillment-order-
    created-sub              created-sub
    (inventory svc)          (fulfillment svc)

    [test] ──publish──> fulfillment-events
                             │
                    order-fulfillment-
                    assigned-sub
                    (order svc)

Each test uses unique topic/subscription names (prefixed with a test run UUID)
so they are isolated and do not interfere with each other or existing infra.
"""

import json
import os
import time
import uuid

import pytest

from tests.integration.conftest import (
    ensure_subscription,
    ensure_topic,
    pull_messages,
)

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def build_order_created_envelope(order_id: int, customer_id: str = "cust-001") -> dict:
    from shared.events.envelope import EventEnvelope
    from shared.events.order_events import ORDER_CREATED, OrderCreatedData, OrderItemData
    from decimal import Decimal

    data = OrderCreatedData(
        order_id=order_id,
        customer_id=customer_id,
        items=[
            OrderItemData(
                product_id=1,
                sku="SKU-TEST-001",
                quantity=2,
                unit_price=Decimal("19.99"),
            )
        ],
        total_amount=Decimal("39.98"),
    )
    env = EventEnvelope(
        event_type=ORDER_CREATED,
        source="order-service",
        data=data.model_dump(mode="json"),
    )
    return env


def build_fulfillment_assigned_envelope(order_id: int, fulfillment_id: int = 1) -> dict:
    from shared.events.envelope import EventEnvelope
    from shared.events.fulfillment_events import FULFILLMENT_ASSIGNED, FulfillmentAssignedData

    data = FulfillmentAssignedData(
        fulfillment_id=fulfillment_id,
        order_id=order_id,
        warehouse_id="warehouse-east",
        carrier="fedex",
        customer_id="cust-001",
        estimated_delivery_days=3,
    )
    env = EventEnvelope(
        event_type=FULFILLMENT_ASSIGNED,
        source="fulfillment-service",
        data=data.model_dump(mode="json"),
    )
    return env


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestOrderCreatedEventFlow:
    """order.created events should be consumable by inventory and fulfillment."""

    @pytest.fixture(autouse=True)
    def setup_topics_and_subs(
        self,
        pubsub_publisher,
        pubsub_subscriber_client,
        gcp_project_id,
    ):
        """Create isolated test topics/subscriptions for this test class."""
        run_id = uuid.uuid4().hex[:8]
        self.topic_name = f"order-events-test-{run_id}"
        self.dlq_topic_name = f"order-events-dlq-test-{run_id}"
        self.inventory_sub_name = f"inventory-order-created-test-{run_id}"
        self.fulfillment_sub_name = f"fulfillment-order-created-test-{run_id}"
        self.project_id = gcp_project_id
        self.publisher = pubsub_publisher
        self.subscriber = pubsub_subscriber_client

        # Create main topic + DLQ topic
        ensure_topic(pubsub_publisher, gcp_project_id, self.topic_name)
        ensure_topic(pubsub_publisher, gcp_project_id, self.dlq_topic_name)

        # Create two subscribers (simulating inventory + fulfillment services)
        ensure_subscription(
            pubsub_subscriber_client,
            pubsub_publisher,
            gcp_project_id,
            self.inventory_sub_name,
            self.topic_name,
            self.dlq_topic_name,
        )
        ensure_subscription(
            pubsub_subscriber_client,
            pubsub_publisher,
            gcp_project_id,
            self.fulfillment_sub_name,
            self.topic_name,
            self.dlq_topic_name,
        )
        yield
        # Cleanup
        try:
            self.subscriber.delete_subscription(
                request={"subscription": self.subscriber.subscription_path(gcp_project_id, self.inventory_sub_name)}
            )
            self.subscriber.delete_subscription(
                request={"subscription": self.subscriber.subscription_path(gcp_project_id, self.fulfillment_sub_name)}
            )
            self.publisher.delete_topic(
                request={"topic": self.publisher.topic_path(gcp_project_id, self.topic_name)}
            )
            self.publisher.delete_topic(
                request={"topic": self.publisher.topic_path(gcp_project_id, self.dlq_topic_name)}
            )
        except Exception:
            pass

    def test_order_created_event_published_and_consumable(self):
        """Publishing order.created should make it available to both subscribers."""
        order_id = int(uuid.uuid4().int % 100000)
        envelope = build_order_created_envelope(order_id)
        topic_path = self.publisher.topic_path(self.project_id, self.topic_name)

        # Publish the event
        data = envelope.to_json_bytes()
        future = self.publisher.publish(
            topic_path,
            data,
            event_type=envelope.event_type,
            source=envelope.source,
        )
        future.result(timeout=10)  # confirm publish succeeded

        # Both subscribers should receive the message independently
        inventory_messages = pull_messages(
            self.subscriber, self.project_id, self.inventory_sub_name, expected_count=1
        )
        fulfillment_messages = pull_messages(
            self.subscriber, self.project_id, self.fulfillment_sub_name, expected_count=1
        )

        assert len(inventory_messages) == 1, "Inventory subscriber should receive order.created"
        assert len(fulfillment_messages) == 1, "Fulfillment subscriber should receive order.created"

        # Validate envelope structure
        inv_env = inventory_messages[0]
        assert inv_env["event_type"] == "order.created"
        assert inv_env["source"] == "order-service"
        assert inv_env["data"]["order_id"] == order_id
        assert inv_env["data"]["customer_id"] == "cust-001"
        assert len(inv_env["data"]["items"]) == 1

        # Both subscribers got the same event content
        assert inventory_messages[0]["event_id"] == fulfillment_messages[0]["event_id"]

    def test_order_created_event_has_valid_envelope_schema(self):
        """The published message should deserialise into EventEnvelope without error."""
        from shared.events.envelope import EventEnvelope
        from shared.events.order_events import OrderCreatedData

        order_id = int(uuid.uuid4().int % 100000)
        envelope = build_order_created_envelope(order_id)
        topic_path = self.publisher.topic_path(self.project_id, self.topic_name)

        future = self.publisher.publish(topic_path, envelope.to_json_bytes())
        future.result(timeout=10)

        messages = pull_messages(
            self.subscriber, self.project_id, self.inventory_sub_name, expected_count=1
        )
        assert len(messages) == 1

        # Full round-trip: raw bytes → EventEnvelope → OrderCreatedData
        raw_bytes = json.dumps(messages[0]).encode()
        parsed_env = EventEnvelope.from_json_bytes(raw_bytes)
        order_data = OrderCreatedData(**parsed_env.data)

        assert order_data.order_id == order_id
        assert order_data.customer_id == "cust-001"
        assert order_data.items[0].sku == "SKU-TEST-001"


class TestFulfillmentAssignedEventFlow:
    """fulfillment.assigned events should be consumable by the order service."""

    @pytest.fixture(autouse=True)
    def setup_topics_and_subs(
        self,
        pubsub_publisher,
        pubsub_subscriber_client,
        gcp_project_id,
    ):
        run_id = uuid.uuid4().hex[:8]
        self.topic_name = f"fulfillment-events-test-{run_id}"
        self.dlq_topic_name = f"fulfillment-events-dlq-test-{run_id}"
        self.order_sub_name = f"order-fulfillment-assigned-test-{run_id}"
        self.project_id = gcp_project_id
        self.publisher = pubsub_publisher
        self.subscriber = pubsub_subscriber_client

        ensure_topic(pubsub_publisher, gcp_project_id, self.topic_name)
        ensure_topic(pubsub_publisher, gcp_project_id, self.dlq_topic_name)
        ensure_subscription(
            pubsub_subscriber_client,
            pubsub_publisher,
            gcp_project_id,
            self.order_sub_name,
            self.topic_name,
            self.dlq_topic_name,
        )
        yield
        try:
            self.subscriber.delete_subscription(
                request={"subscription": self.subscriber.subscription_path(gcp_project_id, self.order_sub_name)}
            )
            self.publisher.delete_topic(
                request={"topic": self.publisher.topic_path(gcp_project_id, self.topic_name)}
            )
            self.publisher.delete_topic(
                request={"topic": self.publisher.topic_path(gcp_project_id, self.dlq_topic_name)}
            )
        except Exception:
            pass

    def test_fulfillment_assigned_event_consumable_by_order_service(self):
        """Order service subscriber should receive fulfillment.assigned events."""
        order_id = int(uuid.uuid4().int % 100000)
        envelope = build_fulfillment_assigned_envelope(order_id, fulfillment_id=42)
        topic_path = self.publisher.topic_path(self.project_id, self.topic_name)

        future = self.publisher.publish(
            topic_path,
            envelope.to_json_bytes(),
            event_type=envelope.event_type,
            source=envelope.source,
        )
        future.result(timeout=10)

        messages = pull_messages(
            self.subscriber, self.project_id, self.order_sub_name, expected_count=1
        )

        assert len(messages) == 1
        msg = messages[0]
        assert msg["event_type"] == "fulfillment.assigned"
        assert msg["source"] == "fulfillment-service"
        assert msg["data"]["order_id"] == order_id
        assert msg["data"]["fulfillment_id"] == 42
        assert msg["data"]["carrier"] == "fedex"

    def test_fulfillment_assigned_deserialises_to_schema(self):
        """Round-trip: fulfillment.assigned → EventEnvelope → FulfillmentAssignedData."""
        from shared.events.envelope import EventEnvelope
        from shared.events.fulfillment_events import FulfillmentAssignedData

        order_id = int(uuid.uuid4().int % 100000)
        envelope = build_fulfillment_assigned_envelope(order_id)
        topic_path = self.publisher.topic_path(self.project_id, self.topic_name)

        future = self.publisher.publish(topic_path, envelope.to_json_bytes())
        future.result(timeout=10)

        messages = pull_messages(
            self.subscriber, self.project_id, self.order_sub_name, expected_count=1
        )
        assert len(messages) == 1

        raw_bytes = json.dumps(messages[0]).encode()
        parsed_env = EventEnvelope.from_json_bytes(raw_bytes)
        assigned_data = FulfillmentAssignedData(**parsed_env.data)

        assert assigned_data.order_id == order_id
        assert assigned_data.warehouse_id == "warehouse-east"
        assert assigned_data.estimated_delivery_days == 3


class TestEventEnvelopeIdempotency:
    """Each published event must have a unique event_id (used for idempotency)."""

    @pytest.fixture(autouse=True)
    def setup_topics_and_subs(
        self,
        pubsub_publisher,
        pubsub_subscriber_client,
        gcp_project_id,
    ):
        run_id = uuid.uuid4().hex[:8]
        self.topic_name = f"order-events-idem-test-{run_id}"
        self.sub_name = f"idem-sub-test-{run_id}"
        self.project_id = gcp_project_id
        self.publisher = pubsub_publisher
        self.subscriber = pubsub_subscriber_client

        ensure_topic(pubsub_publisher, gcp_project_id, self.topic_name)
        ensure_subscription(
            pubsub_subscriber_client,
            pubsub_publisher,
            gcp_project_id,
            self.sub_name,
            self.topic_name,
        )
        yield
        try:
            self.subscriber.delete_subscription(
                request={"subscription": self.subscriber.subscription_path(gcp_project_id, self.sub_name)}
            )
            self.publisher.delete_topic(
                request={"topic": self.publisher.topic_path(gcp_project_id, self.topic_name)}
            )
        except Exception:
            pass

    def test_multiple_events_have_unique_event_ids(self):
        """Publishing 5 events should yield 5 distinct event_ids."""
        topic_path = self.publisher.topic_path(self.project_id, self.topic_name)
        published_ids = []

        for i in range(5):
            env = build_order_created_envelope(order_id=i + 1000)
            published_ids.append(env.event_id)
            future = self.publisher.publish(topic_path, env.to_json_bytes())
            future.result(timeout=10)

        received = pull_messages(
            self.subscriber, self.project_id, self.sub_name, expected_count=5, timeout_seconds=20
        )
        assert len(received) == 5

        received_ids = [m["event_id"] for m in received]
        assert len(set(received_ids)) == 5, "All event_ids must be unique"

        # The event_ids we published should match what was received (order may differ)
        assert set(published_ids) == set(received_ids)
