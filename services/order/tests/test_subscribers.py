"""
Unit tests for order service Pub/Sub event subscribers.

Tests both fulfillment_assigned and fulfillment_completed subscriber handlers,
verifying state transitions and idempotency behaviour.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shared.events.envelope import EventEnvelope
from shared.events.fulfillment_events import (
    FULFILLMENT_ASSIGNED,
    FULFILLMENT_COMPLETED,
    FulfillmentAssignedData,
    FulfillmentCompletedData,
)


def _mock_session_factory(session):
    """Return a callable that acts as AsyncSessionLocal context manager."""
    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=session)
    mock_cm.__aexit__ = AsyncMock(return_value=None)
    return MagicMock(return_value=mock_cm)


def make_fulfillment_assigned_envelope(order_id: int = 10, fulfillment_id: int = 99) -> EventEnvelope:
    data = FulfillmentAssignedData(
        fulfillment_id=fulfillment_id,
        order_id=order_id,
        warehouse_id="warehouse-east",
        carrier="ups",
        customer_id="cust-001",
        estimated_delivery_days=3,
    )
    return EventEnvelope(
        event_type=FULFILLMENT_ASSIGNED,
        source="fulfillment-service",
        data=data.model_dump(mode="json"),
    )


def make_fulfillment_completed_envelope(order_id: int = 10, fulfillment_id: int = 99) -> EventEnvelope:
    data = FulfillmentCompletedData(
        fulfillment_id=fulfillment_id,
        order_id=order_id,
        tracking_number="1Z-TRACK-123",
        carrier="ups",
        customer_id="cust-001",
    )
    return EventEnvelope(
        event_type=FULFILLMENT_COMPLETED,
        source="fulfillment-service",
        data=data.model_dump(mode="json"),
    )


# ── FulfillmentAssignedSubscriber ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fulfillment_assigned_updates_order_to_processing(db_session):
    """fulfillment.assigned should transition order status to PROCESSING."""
    from app.subscribers.fulfillment_assigned import FulfillmentAssignedSubscriber
    from app.services.order_service import OrderService
    from app.models.order import OrderStatus
    import respx, httpx

    # Create a CONFIRMED order in DB
    from app.schemas.order import OrderCreate, OrderItemCreate
    from decimal import Decimal
    from tests.conftest import INVENTORY_BASE

    svc = OrderService(db=db_session, inventory_base_url=INVENTORY_BASE)

    with respx.mock(base_url=INVENTORY_BASE, assert_all_mocked=False, assert_all_called=False) as mock:
        mock.get("/api/v1/products/1").mock(
            return_value=httpx.Response(200, json={"id": 1, "quantity_on_hand": 50})
        )
        mock.post("/api/v1/products/1/reserve").mock(
            return_value=httpx.Response(200, json={"reserved": True})
        )
        order_data = OrderCreate(
            customer_id="cust-sub-test",
            shipping_address="123 Sub Test St",
            items=[OrderItemCreate(product_id=1, sku="SKU-001", quantity=1, unit_price=Decimal("9.99"))],
        )
        order = await svc.create_order(order_data)
        await db_session.commit()

    assert order.status == OrderStatus.CONFIRMED.value

    envelope = make_fulfillment_assigned_envelope(order_id=order.id)

    sub = FulfillmentAssignedSubscriber(project_id="test-project")

    with patch("app.database.AsyncSessionLocal", _mock_session_factory(db_session)), \
         patch("shared.db.idempotency.is_already_processed", new_callable=AsyncMock, return_value=False), \
         patch("shared.db.idempotency.mark_processed", new_callable=AsyncMock):
        await sub._update_order(order.id, envelope.event_id)

    await db_session.refresh(order)
    assert order.status == OrderStatus.PROCESSING.value


@pytest.mark.asyncio
async def test_fulfillment_assigned_skips_duplicate():
    """Duplicate fulfillment.assigned events should be silently skipped."""
    from app.subscribers.fulfillment_assigned import FulfillmentAssignedSubscriber

    sub = FulfillmentAssignedSubscriber(project_id="test-project")
    envelope = make_fulfillment_assigned_envelope(order_id=999)

    with patch("app.database.AsyncSessionLocal", _mock_session_factory(AsyncMock())), \
         patch("shared.db.idempotency.is_already_processed", new_callable=AsyncMock, return_value=True), \
         patch("shared.db.idempotency.mark_processed", new_callable=AsyncMock) as mock_mark:
        await sub._update_order(999, envelope.event_id)
        mock_mark.assert_not_called()


@pytest.mark.asyncio
async def test_fulfillment_assigned_ignores_wrong_event_type():
    """Events with wrong event_type should be silently ignored."""
    from app.subscribers.fulfillment_assigned import FulfillmentAssignedSubscriber

    sub = FulfillmentAssignedSubscriber(project_id="test-project")
    envelope = EventEnvelope(event_type="some.other", source="x", data={})

    with patch("asyncio.run") as mock_run:
        sub.handle(envelope)
        mock_run.assert_not_called()


# ── FulfillmentCompletedSubscriber ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fulfillment_completed_updates_order_to_completed(db_session):
    """fulfillment.completed should transition order status to COMPLETED."""
    from app.subscribers.fulfillment_completed import FulfillmentCompletedSubscriber
    from app.services.order_service import OrderService
    from app.models.order import Order, OrderStatus
    import respx, httpx

    from app.schemas.order import OrderCreate, OrderItemCreate
    from decimal import Decimal
    from tests.conftest import INVENTORY_BASE

    svc = OrderService(db=db_session, inventory_base_url=INVENTORY_BASE)

    with respx.mock(base_url=INVENTORY_BASE, assert_all_mocked=False, assert_all_called=False) as mock:
        mock.get("/api/v1/products/1").mock(
            return_value=httpx.Response(200, json={"id": 1, "quantity_on_hand": 50})
        )
        mock.post("/api/v1/products/1/reserve").mock(
            return_value=httpx.Response(200, json={"reserved": True})
        )
        order = await svc.create_order(
            OrderCreate(
                customer_id="cust-completed-test",
                shipping_address="789 Completed Ave",
                items=[OrderItemCreate(product_id=1, sku="SKU-001", quantity=1, unit_price=Decimal("9.99"))],
            )
        )
        await db_session.commit()

    # Manually advance to PROCESSING (simulating fulfillment.assigned was processed)
    await svc.update_status(order.id, OrderStatus.PROCESSING)
    await db_session.commit()

    envelope = make_fulfillment_completed_envelope(order_id=order.id)
    sub = FulfillmentCompletedSubscriber(project_id="test-project")

    with patch("app.database.AsyncSessionLocal", _mock_session_factory(db_session)), \
         patch("shared.db.idempotency.is_already_processed", new_callable=AsyncMock, return_value=False), \
         patch("shared.db.idempotency.mark_processed", new_callable=AsyncMock):
        data = FulfillmentCompletedData(**envelope.data)
        await sub._complete_order(data, envelope.event_id)

    await db_session.refresh(order)
    assert order.status == OrderStatus.DELIVERED.value


@pytest.mark.asyncio
async def test_fulfillment_completed_skips_duplicate():
    """Duplicate fulfillment.completed events should be silently skipped."""
    from app.subscribers.fulfillment_completed import FulfillmentCompletedSubscriber

    sub = FulfillmentCompletedSubscriber(project_id="test-project")
    envelope = make_fulfillment_completed_envelope(order_id=998)

    with patch("app.database.AsyncSessionLocal", _mock_session_factory(AsyncMock())), \
         patch("shared.db.idempotency.is_already_processed", new_callable=AsyncMock, return_value=True), \
         patch("shared.db.idempotency.mark_processed", new_callable=AsyncMock) as mock_mark:
        data = FulfillmentCompletedData(**envelope.data)
        await sub._complete_order(data, envelope.event_id)
        mock_mark.assert_not_called()


@pytest.mark.asyncio
async def test_fulfillment_completed_ignores_wrong_event_type():
    """Events with wrong event_type should be silently ignored."""
    from app.subscribers.fulfillment_completed import FulfillmentCompletedSubscriber

    sub = FulfillmentCompletedSubscriber(project_id="test-project")
    envelope = EventEnvelope(event_type="some.other", source="x", data={})

    with patch("asyncio.run") as mock_run:
        sub.handle(envelope)
        mock_run.assert_not_called()
