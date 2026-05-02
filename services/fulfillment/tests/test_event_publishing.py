"""
Unit tests for fulfillment event publishing.

Tests that:
  - create_from_order publishes fulfillment.assigned on success
  - mark_completed publishes fulfillment.completed
  - Events are not published when no publisher is configured
  - FulfillmentCompletedSubscriber (order_created) handles idempotency
"""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shared.events.envelope import EventEnvelope
from shared.events.order_events import ORDER_CREATED, OrderCreatedData, OrderItemData
from shared.events.fulfillment_events import FULFILLMENT_ASSIGNED, FULFILLMENT_COMPLETED

from app.services.fulfillment_service import FulfillmentService
from app.models.fulfillment import FulfillmentStatus


def _mock_session_factory(session):
    """Return a callable acting as AsyncSessionLocal context manager."""
    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=session)
    mock_cm.__aexit__ = AsyncMock(return_value=None)
    return MagicMock(return_value=mock_cm)


# ── Event publishing tests ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_fulfillment_publishes_assigned_event(db_session):
    """create_from_order should publish a fulfillment.assigned event."""
    published = []
    svc = FulfillmentService(db=db_session, pubsub_publisher=lambda e: published.append(e))

    await svc.create_from_order(order_id=300, customer_id="cust-pub-test")
    await db_session.commit()

    assert len(published) == 1
    evt = published[0]
    assert evt.event_type == FULFILLMENT_ASSIGNED
    assert evt.source == "fulfillment-service"
    assert evt.data["order_id"] == 300
    assert evt.data["warehouse_id"] is not None
    assert evt.data["carrier"] is not None


@pytest.mark.asyncio
async def test_create_fulfillment_no_publisher(db_session):
    """create_from_order should succeed without a publisher configured."""
    svc = FulfillmentService(db=db_session, pubsub_publisher=None)
    f = await svc.create_from_order(order_id=301, customer_id="cust-no-pub")
    await db_session.commit()
    assert f.id is not None


@pytest.mark.asyncio
async def test_mark_completed_publishes_fulfillment_completed(db_session):
    """mark_completed should publish a fulfillment.completed event."""
    published = []
    svc = FulfillmentService(db=db_session, pubsub_publisher=lambda e: published.append(e))

    f = await svc.create_from_order(order_id=302, customer_id="cust-complete")
    await svc.start_picking(f.id)
    from app.schemas.fulfillment import MarkShippedRequest
    await svc.mark_shipped(f.id, MarkShippedRequest(tracking_number="TRK-COMPLETE-001"))
    await svc.mark_completed(f.id)
    await db_session.commit()

    # Two events: assigned + completed
    assert len(published) == 2
    assert published[0].event_type == FULFILLMENT_ASSIGNED
    completed_evt = published[1]
    assert completed_evt.event_type == FULFILLMENT_COMPLETED
    assert completed_evt.data["order_id"] == 302
    assert completed_evt.data["tracking_number"] == "TRK-COMPLETE-001"


@pytest.mark.asyncio
async def test_mark_completed_no_publisher(db_session):
    """mark_completed should succeed without a publisher."""
    svc = FulfillmentService(db=db_session, pubsub_publisher=None)
    f = await svc.create_from_order(order_id=303, customer_id="cust-nopub2")
    await svc.start_picking(f.id)
    from app.schemas.fulfillment import MarkShippedRequest
    await svc.mark_shipped(f.id, MarkShippedRequest(tracking_number="TRK-NP"))
    f = await svc.mark_completed(f.id)
    assert f.status == FulfillmentStatus.COMPLETED.value


@pytest.mark.asyncio
async def test_assigned_event_has_warehouse_and_carrier(db_session):
    """fulfillment.assigned event should contain warehouse_id and carrier."""
    published = []
    svc = FulfillmentService(db=db_session, pubsub_publisher=lambda e: published.append(e))
    await svc.create_from_order(order_id=304, customer_id="cust-fields")
    await db_session.commit()

    evt = published[0]
    assert "warehouse_id" in evt.data
    assert "carrier" in evt.data
    assert evt.data["carrier"] in ("fedex", "ups", "dhl")


# ── OrderCreatedSubscriber (fulfillment) ──────────────────────────────────────

def make_order_created_envelope(order_id: int = 400) -> EventEnvelope:
    data = OrderCreatedData(
        order_id=order_id,
        customer_id="cust-fulfillment-sub",
        shipping_address="456 Fulfillment Ave",
        items=[OrderItemData(product_id=1, sku="SKU-F01", quantity=2, unit_price=Decimal("5.00"))],
        total_amount=Decimal("10.00"),
    )
    return EventEnvelope(
        event_type=ORDER_CREATED,
        source="order-service",
        data=data.model_dump(mode="json"),
    )


@pytest.mark.asyncio
async def test_order_created_subscriber_creates_fulfillment(db_session):
    """order.created → creates a fulfillment record via FulfillmentService."""
    from app.subscribers.order_created import OrderCreatedSubscriber

    envelope = make_order_created_envelope(order_id=400)
    sub = OrderCreatedSubscriber(project_id="test-project")

    with patch("app.database.AsyncSessionLocal", _mock_session_factory(db_session)), \
         patch("shared.db.idempotency.is_already_processed", new_callable=AsyncMock, return_value=False), \
         patch("shared.db.idempotency.mark_processed", new_callable=AsyncMock):
        data = OrderCreatedData(**envelope.data)
        await sub._create_fulfillment(data, envelope.event_id)

    # Verify fulfillment was created
    from sqlalchemy import select
    from app.models.fulfillment import Fulfillment
    result = await db_session.execute(
        select(Fulfillment).where(Fulfillment.order_id == 400)
    )
    f = result.scalar_one_or_none()
    assert f is not None
    assert f.status == "assigned"
    assert f.customer_id == "cust-fulfillment-sub"


@pytest.mark.asyncio
async def test_order_created_subscriber_event_idempotency(db_session):
    """Event-level idempotency: already-processed events skip fulfillment creation."""
    from app.subscribers.order_created import OrderCreatedSubscriber

    envelope = make_order_created_envelope(order_id=401)
    sub = OrderCreatedSubscriber(project_id="test-project")

    with patch("app.database.AsyncSessionLocal", _mock_session_factory(db_session)), \
         patch("shared.db.idempotency.is_already_processed", new_callable=AsyncMock, return_value=True), \
         patch("shared.db.idempotency.mark_processed", new_callable=AsyncMock) as mock_mark:
        data = OrderCreatedData(**envelope.data)
        await sub._create_fulfillment(data, envelope.event_id)
        mock_mark.assert_not_called()

    # No fulfillment created
    from sqlalchemy import select, func
    from app.models.fulfillment import Fulfillment
    count = await db_session.scalar(
        select(func.count()).select_from(Fulfillment).where(Fulfillment.order_id == 401)
    )
    assert count == 0


@pytest.mark.asyncio
async def test_order_created_subscriber_skips_already_processed(db_session):
    """Event-level idempotency: already-processed events should be skipped."""
    from app.subscribers.order_created import OrderCreatedSubscriber

    envelope = make_order_created_envelope(order_id=402)
    sub = OrderCreatedSubscriber(project_id="test-project")

    with patch("app.database.AsyncSessionLocal", _mock_session_factory(db_session)), \
         patch("shared.db.idempotency.is_already_processed", new_callable=AsyncMock, return_value=True), \
         patch("shared.db.idempotency.mark_processed", new_callable=AsyncMock) as mock_mark:
        data = OrderCreatedData(**envelope.data)
        await sub._create_fulfillment(data, envelope.event_id)
        mock_mark.assert_not_called()
