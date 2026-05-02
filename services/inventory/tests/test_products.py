"""
Product CRUD and stock operation tests.

Each test is isolated: the in-memory SQLite DB is recreated per function
(see conftest.py).  Tests cover:
  - Happy-path CRUD
  - Validation errors (422)
  - Not-found errors (404)
  - Duplicate SKU conflict (409)
  - Stock reservation and release
  - Insufficient stock guard
  - Low-stock flag detection
"""

import pytest
from httpx import AsyncClient

from tests.conftest import make_product


# ── Helper ────────────────────────────────────────────────────────────────────

async def create_one(client: AsyncClient, **overrides) -> dict:
    """Create a product and return the parsed response body."""
    r = await client.post("/api/v1/products", json=make_product(**overrides))
    assert r.status_code == 201, r.text
    return r.json()


# ── CRUD ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_product(client: AsyncClient) -> None:
    body = await create_one(client)
    assert body["id"] > 0
    assert body["sku"] == "NOON-ELEC-001"
    assert body["quantity_on_hand"] == 50
    assert body["quantity_reserved"] == 0
    assert body["version"] == 1
    assert body["is_low_stock"] is False


@pytest.mark.asyncio
async def test_get_product(client: AsyncClient) -> None:
    created = await create_one(client)
    r = await client.get(f"/api/v1/products/{created['id']}")
    assert r.status_code == 200
    assert r.json()["sku"] == created["sku"]


@pytest.mark.asyncio
async def test_get_product_not_found(client: AsyncClient) -> None:
    r = await client.get("/api/v1/products/999999")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_list_products_empty(client: AsyncClient) -> None:
    r = await client.get("/api/v1/products")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 0
    assert body["items"] == []


@pytest.mark.asyncio
async def test_list_products_pagination(client: AsyncClient) -> None:
    # Create 3 products
    for i in range(3):
        await create_one(client, sku=f"SKU-{i:03d}")

    r = await client.get("/api/v1/products?page=1&page_size=2")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2
    assert body["total_pages"] == 2


@pytest.mark.asyncio
async def test_list_products_category_filter(client: AsyncClient) -> None:
    await create_one(client, sku="ELEC-001", category="electronics")
    await create_one(client, sku="FASH-001", category="fashion")

    r = await client.get("/api/v1/products?category=electronics")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["category"] == "electronics"


@pytest.mark.asyncio
async def test_update_product(client: AsyncClient) -> None:
    created = await create_one(client)
    r = await client.put(
        f"/api/v1/products/{created['id']}",
        json={"name": "Updated TV Name", "unit_price": "2499.00"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Updated TV Name"
    assert float(body["unit_price"]) == 2499.00
    assert body["version"] == created["version"] + 1  # version bumped


@pytest.mark.asyncio
async def test_update_product_not_found(client: AsyncClient) -> None:
    r = await client.put("/api/v1/products/999999", json={"name": "Ghost"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_product(client: AsyncClient) -> None:
    created = await create_one(client)
    r = await client.delete(f"/api/v1/products/{created['id']}")
    assert r.status_code == 204

    # Subsequent GET must return 404
    r2 = await client.get(f"/api/v1/products/{created['id']}")
    assert r2.status_code == 404


@pytest.mark.asyncio
async def test_delete_product_not_found(client: AsyncClient) -> None:
    r = await client.delete("/api/v1/products/999999")
    assert r.status_code == 404


# ── Validation ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_product_invalid_price(client: AsyncClient) -> None:
    r = await client.post("/api/v1/products", json=make_product(unit_price="-10"))
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_create_product_negative_quantity(client: AsyncClient) -> None:
    r = await client.post("/api/v1/products", json=make_product(quantity_available=-1))
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_create_product_missing_required_field(client: AsyncClient) -> None:
    payload = make_product()
    del payload["sku"]
    r = await client.post("/api/v1/products", json=payload)
    assert r.status_code == 422


# ── Duplicate SKU ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_duplicate_sku(client: AsyncClient) -> None:
    await create_one(client, sku="DUPE-001")
    r = await client.post("/api/v1/products", json=make_product(sku="DUPE-001"))
    assert r.status_code == 409
    assert "already exists" in r.json()["detail"]


# ── Stock reservation ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reserve_stock(client: AsyncClient) -> None:
    created = await create_one(client, quantity_available=20)
    r = await client.post(
        f"/api/v1/products/{created['id']}/reserve",
        json={"quantity": 5, "order_id": "ORD-001"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["quantity_reserved"] == 5
    assert body["quantity_on_hand"] == 15
    assert body["quantity_delta"] == 5
    assert body["order_id"] == "ORD-001"


@pytest.mark.asyncio
async def test_reserve_stock_insufficient(client: AsyncClient) -> None:
    created = await create_one(client, quantity_available=3)
    r = await client.post(
        f"/api/v1/products/{created['id']}/reserve",
        json={"quantity": 10, "order_id": "ORD-002"},
    )
    assert r.status_code == 409
    assert "Insufficient stock" in r.json()["detail"]


@pytest.mark.asyncio
async def test_reserve_stock_product_not_found(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/products/999999/reserve",
        json={"quantity": 1, "order_id": "ORD-003"},
    )
    assert r.status_code == 404


# ── Stock release ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_release_stock(client: AsyncClient) -> None:
    created = await create_one(client, quantity_available=20)
    pid = created["id"]

    # First reserve 5
    await client.post(
        f"/api/v1/products/{pid}/reserve",
        json={"quantity": 5, "order_id": "ORD-010"},
    )

    # Then release 3
    r = await client.post(
        f"/api/v1/products/{pid}/release",
        json={"quantity": 3, "order_id": "ORD-010"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["quantity_reserved"] == 2
    assert body["quantity_on_hand"] == 18
    assert body["quantity_delta"] == -3


@pytest.mark.asyncio
async def test_release_more_than_reserved(client: AsyncClient) -> None:
    created = await create_one(client, quantity_available=20)
    r = await client.post(
        f"/api/v1/products/{created['id']}/release",
        json={"quantity": 5, "order_id": "ORD-011"},
    )
    assert r.status_code == 409
    assert "Cannot release" in r.json()["detail"]


# ── Low-stock flag ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_low_stock_flag(client: AsyncClient) -> None:
    """Reserving down to reorder_point should set is_low_stock=True."""
    created = await create_one(client, quantity_available=12, reorder_point=10)
    pid = created["id"]

    # Reserve 2 units → on_hand = 10 = reorder_point → is_low_stock=True
    r = await client.post(
        f"/api/v1/products/{pid}/reserve",
        json={"quantity": 2, "order_id": "ORD-LOW"},
    )
    assert r.status_code == 200
    assert r.json()["is_low_stock"] is True


@pytest.mark.asyncio
async def test_low_stock_filter(client: AsyncClient) -> None:
    # Product 1: plenty of stock
    await create_one(client, sku="GOOD-001", quantity_available=100, reorder_point=5)
    # Product 2: low stock (on_hand = 3, reorder = 5)
    await create_one(client, sku="LOW-001", quantity_available=3, reorder_point=5)

    r = await client.get("/api/v1/products?low_stock_only=true")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["sku"] == "LOW-001"
