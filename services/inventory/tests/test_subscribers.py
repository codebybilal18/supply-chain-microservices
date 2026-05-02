"""
Unit tests for inventory Pub/Sub event subscribers.

Since all imports inside _reserve_all / _record_completion are lazy (inside
the async method body), patches must target the *source* modules:
  - app.database.AsyncSessionLocal
  - shared.db.idempotency.is_already_processed
  - shared.db.idempotency.mark_processed
"""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shared.events.envelope import EventEnvelope
from shared.events.order_events import ORDER_CREATED, OrderCreatedData, OrderItemData
from shared.events.fulfillment_events import FULFILLMENT_COMPLETED, FulfillmentCompletedData
from shared.events.inventory_events import STOCK_RESERVED


def make_order_created_envelope(order_id: int = 101) -> EventEnvelope:
    data = OrderCreatedData(
        order_id=order_id,
        customer_id="cust-test",
        shipping_address="123 Test St",
        items=[
            OrderItemData(product_id=1, sku="SKU-001", quantity=3, unit_price=Decimal("9.99")),
            OrderItemData(product_id=2, sku="SKU-002", quantity=1, unit_price=Decimal("49.99")),
        ],
        total_amount=Decimal("79.96"),
    )
    return EventEnvelope(
        event_type=ORDER_CREATED,
        source="order-service",
        data=data.model_dump(mode="json"),
    )


def make_fulfillment_completed_envelope(order_id: int = 200) -> EventEnvelope:
    data = FulfillmentCompletedData(
        fulfillment_id=55, order_id=order_id,
        tracking_number="TRK-XYZ", carrier="fedex", customer_id="cust-test",
    )
    return EventEnvelope(
        event_type=FULFILLMENT_COMPLETED,
        source="fulfillment-service",
        data=data.model_dump(mode="json"),
    )


def _mock_session_factory(session):
    """Return a callable that acts as AsyncSessionLocal context manager."""
    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=session)
    mock_cm.__aexit__ = AsyncMock(return_value=None)
    return MagicMock(return_value=mock_cm)


# -- OrderCreatedSubscriber ---------------------------------------------------

@pytest.mark.asyncio
async def test_order_created_subscriber_reserves_and_publishes(db_session):
    """Subscriber reserves stock for every item and publishes stock_reserved."""
    from app.schemas.product import ProductCreate
    from app.services.inventory_service import InventoryService
    from app.subscribers.order_created import OrderCreatedSubscriber
    from tests.conftest import make_product

    svc = InventoryService(db=db_session)
    p1 = await svc.create_product(ProductCreate(**make_product(sku="SKU-001", quantity_available=10)))
    p2 = await svc.create_product(ProductCreate(**make_product(sku="SKU-002", quantity_available=10)))
    await db_session.commit()

    published = []
    sub = OrderCreatedSubscriber(project_id="test-project", publisher=lambda e: published.append(e))

    envelope = make_order_created_envelope(order_id=101)
    envelope.data["items"][0]["product_id"] = p1.id
    envelope.data["items"][1]["product_id"] = p2.id
    order_data = OrderCreatedData(**envelope.data)

    with patch("app.database.AsyncSessionLocal", _mock_session_factory(db_session)), \
         patch("shared.db.idempotency.is_already_processed", new_callable=AsyncMock, return_value=False), \
         patch("shared.db.idempotency.mark_processed", new_callable=AsyncMock):
        await sub._reserve_all(order_data, envelope.event_id)

    await db_session.refresh(p1)
    await db_session.refresh(p2)
    assert p1.quantity_reserved == 3
    assert p2.quantity_reserved == 1

    assert len(published) == 1
    assert published[0].event_type == STOCK_RESERVED
    assert published[0].data["order_id"] == 101
    assert len(published[0].data["reservations"]) == 2


@pytest.mark.asyncio
async def test_order_created_subscriber_skips_duplicate(db_session):
    """Already-processed event_id is silently skipped."""
    from app.subscribers.order_created import OrderCreatedSubscriber

    published = []
    sub = OrderCreatedSubscriber(project_id="test-project", publisher=lambda e: published.append(e))
    envelope = make_order_created_envelope(order_id=102)
    order_data = OrderCreatedData(**envelope.data)

    with patch("app.database.AsyncSessionLocal", _mock_session_factory(db_session)), \
         patch("shared.db.idempotency.is_already_processed", new_callable=AsyncMock, return_value=True):
        await sub._reserve_all(order_data, envelope.event_id)

    assert len(published) == 0


@pytest.mark.asyncio
async def test_order_created_subscriber_ignores_wrong_event_type():
    """Events with a different event_type are silently ignored."""
    from app.subscribers.order_created import OrderCreatedSubscriber

    sub = OrderCreatedSubscriber(project_id="test-project")
    envelope = EventEnvelope(event_type="some.other.event", source="x", data={})
    with patch("asyncio.run") as mock_run:
        sub.handle(envelope)
        mock_run.assert_not_called()


def test_order_created_no_publisher_does_not_raise():
    """_publish_stock_reserved with publisher=None is a no-op."""
    from app.subscribers.order_created import OrderCreatedSubscriber

    sub = OrderCreatedSubscriber(project_id="test-project", publisher=None)
    envelope = make_order_created_envelope(order_id=103)
    sub._publish_stock_reserved(OrderCreatedData(**envelope.data))  # must not raise


@pytest.mark.asyncio
async def test_stock_reserved_event_has_correct_schema():
    """Published stock_reserved event matches the STOCK_RESERVED schema."""
    from app.subscribers.order_created import OrderCreatedSubscriber

    published = []
    sub = OrderCreatedSubscriber(project_id="test-project", publisher=lambda e: published.append(e))
    envelope = make_order_created_envelope(order_id=104)
    sub._publish_stock_reserved(OrderCreatedData(**envelope.data))

    assert len(published) == 1
    evt = published[0]
    assert evt.event_type == STOCK_RESERVED
    assert evt.source == "inventory-service"
    assert "reservations" in evt.data
    for r in evt.data["reservations"]:
        assert "product_id" in r
        assert "sku" in r
        assert "quantity" in r


# -- FulfillmentCompletedSubscriber ------------------------------------------

@pytest.mark.asyncio
async def test_fulfillment_completed_records_event(db_session):
    """fulfillment.completed records the event via mark_processed."""
    from app.subscribers.fulfillment_completed import FulfillmentCompletedSubscriber

    sub = FulfillmentCompletedSubscriber(project_id="test-project")
    envelope = make_fulfillment_completed_envelope(order_id=200)
    data = FulfillmentCompletedData(**envelope.data)

    with patch("app.database.AsyncSessionLocal", _mock_session_factory(db_session)), \
         patch("shared.db.idempotency.is_already_processed", new_callable=AsyncMock, return_value=False), \
         patch("shared.db.idempotency.mark_processed", new_callable=AsyncMock) as mock_mark:
        await sub._record_completion(data, envelope.event_id)
        mock_mark.assert_called_once_with(db_session, "inventory-service", envelope.event_id)


@pytest.mark.asyncio
async def test_fulfillment_completed_skips_duplicate(db_session):
    """Duplicate fulfillment.completed events are silently skipped."""
    from app.subscribers.fulfillment_completed import FulfillmentCompletedSubscriber

    sub = FulfillmentCompletedSubscriber(project_id="test-project")
    envelope = make_fulfillment_completed_envelope(order_id=201)
    data = FulfillmentCompletedData(**envelope.data)

    with patch("app.database.AsyncSessionLocal", _mock_session_factory(db_session)), \
         patch("shared.db.idempotency.is_already_processed", new_callable=AsyncMock, return_value=True), \
         patch("shared.db.idempotency.mark_processed", new_callable=AsyncMock) as mock_mark:
        await sub._record_completion(data, envelope.event_id)
        mock_mark.assert_not_called()
