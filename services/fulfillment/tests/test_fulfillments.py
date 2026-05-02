"""
Fulfillment endpoint tests.

Covers:
  - Create fulfillment from order event (via service layer directly)
  - Get fulfillment by ID
  - Get by order ID
  - List fulfillments
  - Full lifecycle: assigned → picking → shipped → completed
  - Invalid state transition
  - Idempotent create (duplicate order)
  - Mark failed
"""

import pytest
from app.services.fulfillment_service import FulfillmentService
from app.models.fulfillment import FulfillmentStatus


# ── Service-layer tests ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_fulfillment(db_session):
    svc = FulfillmentService(db=db_session)
    f = await svc.create_from_order(
        order_id=1, customer_id="cust-001", shipping_address="123 Main St"
    )
    assert f.id is not None
    assert f.order_id == 1
    assert f.status == "assigned"
    assert f.warehouse_id is not None
    assert f.carrier is not None


@pytest.mark.asyncio
async def test_create_fulfillment_idempotent(db_session):
    svc = FulfillmentService(db=db_session)
    f1 = await svc.create_from_order(order_id=2, customer_id="cust-002")
    f2 = await svc.create_from_order(order_id=2, customer_id="cust-002")
    assert f1.id == f2.id


@pytest.mark.asyncio
async def test_full_lifecycle(db_session):
    svc = FulfillmentService(db=db_session)
    f = await svc.create_from_order(order_id=3, customer_id="cust-003")
    assert f.status == "assigned"

    f = await svc.start_picking(f.id)
    assert f.status == "picking"

    from app.schemas.fulfillment import MarkShippedRequest
    f = await svc.mark_shipped(f.id, MarkShippedRequest(tracking_number="TRK123", carrier="fedex"))
    assert f.status == "shipped"
    assert f.tracking_number == "TRK123"

    f = await svc.mark_completed(f.id)
    assert f.status == "completed"


@pytest.mark.asyncio
async def test_invalid_transition(db_session):
    from app.exceptions import InvalidFulfillmentStateError
    svc = FulfillmentService(db=db_session)
    f = await svc.create_from_order(order_id=4, customer_id="cust-004")

    with pytest.raises(InvalidFulfillmentStateError):
        # Can't go from assigned directly to shipped
        from app.schemas.fulfillment import MarkShippedRequest
        await svc.mark_shipped(f.id, MarkShippedRequest(tracking_number="T"))


@pytest.mark.asyncio
async def test_mark_failed(db_session):
    svc = FulfillmentService(db=db_session)
    f = await svc.create_from_order(order_id=5, customer_id="cust-005")
    f = await svc.mark_failed(f.id, "warehouse flood")
    assert f.status == "failed"
    assert f.failure_reason == "warehouse flood"


@pytest.mark.asyncio
async def test_warehouse_hint(db_session):
    svc = FulfillmentService(db=db_session)
    f = await svc.create_from_order(
        order_id=6, customer_id="cust-006", warehouse_hint="warehouse-west"
    )
    assert f.warehouse_id == "warehouse-west"


# ── API endpoint tests ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_api_get_fulfillment(client, db_session):
    svc = FulfillmentService(db=db_session)
    f = await svc.create_from_order(order_id=10, customer_id="cust-010")
    await db_session.flush()

    r = await client.get(f"/api/v1/fulfillments/{f.id}")
    assert r.status_code == 200
    assert r.json()["order_id"] == 10


@pytest.mark.asyncio
async def test_api_get_by_order(client, db_session):
    svc = FulfillmentService(db=db_session)
    await svc.create_from_order(order_id=11, customer_id="cust-011")
    await db_session.flush()

    r = await client.get("/api/v1/fulfillments/by-order/11")
    assert r.status_code == 200
    assert r.json()["order_id"] == 11


@pytest.mark.asyncio
async def test_api_list_fulfillments_empty(client):
    r = await client.get("/api/v1/fulfillments")
    assert r.status_code == 200
    assert r.json()["total"] == 0


@pytest.mark.asyncio
async def test_api_get_not_found(client):
    r = await client.get("/api/v1/fulfillments/99999")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_api_get_by_order_not_found(client):
    r = await client.get("/api/v1/fulfillments/by-order/99999")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_api_pick_and_ship(client, db_session):
    svc = FulfillmentService(db=db_session)
    f = await svc.create_from_order(order_id=12, customer_id="cust-012")
    await db_session.flush()

    r = await client.post(f"/api/v1/fulfillments/{f.id}/pick")
    assert r.status_code == 200
    assert r.json()["status"] == "picking"

    r = await client.post(
        f"/api/v1/fulfillments/{f.id}/ship",
        json={"tracking_number": "XYZ789"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "shipped"
    assert r.json()["tracking_number"] == "XYZ789"
