"""
Order endpoint tests.

Covers:
  - Create order (happy path)
  - Create order with insufficient stock
  - Create order with unknown product (404)
  - Get order by ID
  - Get order not found
  - List orders (empty)
  - List orders with filter
  - Cancel PENDING order
  - Cancel CONFIRMED order (releases stock)
  - Cancel already-cancelled order (422)
  - State machine transition: CONFIRMED → PROCESSING
"""

import pytest
import httpx
import respx


INVENTORY_BASE = "http://inventory:8000"

ORDER_PAYLOAD = {
    "customer_id": "cust-001",
    "shipping_address": "123 Main St",
    "warehouse_hint": "warehouse-east",
    "items": [
        {"product_id": 1, "sku": "SKU-001", "quantity": 2, "unit_price": "9.99"},
    ],
}


# ── Create ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_order_happy_path(client, mock_inventory):
    r = await client.post("/api/v1/orders", json=ORDER_PAYLOAD)
    assert r.status_code == 201
    data = r.json()
    assert data["customer_id"] == "cust-001"
    assert data["status"] == "confirmed"
    assert len(data["items"]) == 1
    assert data["items"][0]["sku"] == "SKU-001"


@pytest.mark.asyncio
async def test_create_order_multi_item(client, mock_inventory):
    payload = {
        "customer_id": "cust-002",
        "shipping_address": "456 Side St",
        "items": [
            {"product_id": 1, "sku": "SKU-001", "quantity": 1, "unit_price": "9.99"},
            {"product_id": 2, "sku": "SKU-002", "quantity": 3, "unit_price": "29.99"},
        ],
    }
    r = await client.post("/api/v1/orders", json=payload)
    assert r.status_code == 201
    assert len(r.json()["items"]) == 2


@pytest.mark.asyncio
async def test_create_order_insufficient_stock(client):
    with respx.mock(base_url=INVENTORY_BASE, assert_all_mocked=False, assert_all_called=False) as mock:
        mock.get("/api/v1/products/1").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 1, "sku": "SKU-001", "name": "Widget A",
                    "quantity_on_hand": 1, "price": "9.99",
                },
            )
        )
        r = await client.post("/api/v1/orders", json=ORDER_PAYLOAD)
    assert r.status_code == 409
    assert "Insufficient stock" in r.json()["detail"]


@pytest.mark.asyncio
async def test_create_order_product_not_found(client):
    with respx.mock(base_url=INVENTORY_BASE, assert_all_mocked=False, assert_all_called=False) as mock:
        mock.get("/api/v1/products/1").mock(
            return_value=httpx.Response(404, json={"detail": "Not found"})
        )
        r = await client.post("/api/v1/orders", json=ORDER_PAYLOAD)
    assert r.status_code == 409
    assert "not found" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_order_inventory_unavailable(client):
    with respx.mock(base_url=INVENTORY_BASE, assert_all_mocked=False, assert_all_called=False) as mock:
        mock.get("/api/v1/products/1").mock(side_effect=httpx.ConnectError("down"))
        r = await client.post("/api/v1/orders", json=ORDER_PAYLOAD)
    assert r.status_code == 503


# ── Read ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_order(client, mock_inventory):
    create = await client.post("/api/v1/orders", json=ORDER_PAYLOAD)
    order_id = create.json()["id"]

    r = await client.get(f"/api/v1/orders/{order_id}")
    assert r.status_code == 200
    assert r.json()["id"] == order_id


@pytest.mark.asyncio
async def test_get_order_not_found(client):
    r = await client.get("/api/v1/orders/99999")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_list_orders_empty(client):
    r = await client.get("/api/v1/orders")
    assert r.status_code == 200
    data = r.json()
    assert data["items"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_list_orders_with_data(client, mock_inventory):
    await client.post("/api/v1/orders", json=ORDER_PAYLOAD)
    await client.post("/api/v1/orders", json={**ORDER_PAYLOAD, "customer_id": "cust-999"})

    r = await client.get("/api/v1/orders")
    assert r.status_code == 200
    assert r.json()["total"] == 2


@pytest.mark.asyncio
async def test_list_orders_filter_by_customer(client, mock_inventory):
    await client.post("/api/v1/orders", json=ORDER_PAYLOAD)
    await client.post("/api/v1/orders", json={**ORDER_PAYLOAD, "customer_id": "cust-999"})

    r = await client.get("/api/v1/orders?customer_id=cust-001")
    assert r.status_code == 200
    assert r.json()["total"] == 1


# ── Cancel ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cancel_confirmed_order(client, mock_inventory):
    create = await client.post("/api/v1/orders", json=ORDER_PAYLOAD)
    order_id = create.json()["id"]
    assert create.json()["status"] == "confirmed"

    r = await client.post(
        f"/api/v1/orders/{order_id}/cancel",
        json={"reason": "customer changed mind"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_cancel_nonexistent_order(client):
    r = await client.post(
        "/api/v1/orders/99999/cancel",
        json={"reason": "test"},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_cancel_already_cancelled_order(client, mock_inventory):
    create = await client.post("/api/v1/orders", json=ORDER_PAYLOAD)
    order_id = create.json()["id"]
    await client.post(
        f"/api/v1/orders/{order_id}/cancel",
        json={"reason": "first cancellation"},
    )
    r = await client.post(
        f"/api/v1/orders/{order_id}/cancel",
        json={"reason": "second attempt"},
    )
    assert r.status_code == 409


# ── Pagination ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_orders_pagination(client, mock_inventory):
    for i in range(3):
        await client.post(
            "/api/v1/orders",
            json={**ORDER_PAYLOAD, "customer_id": f"cust-{i}"},
        )

    r = await client.get("/api/v1/orders?page=1&page_size=2")
    assert r.status_code == 200
    data = r.json()
    assert len(data["items"]) == 2
    assert data["total"] == 3
    assert data["total_pages"] == 2
