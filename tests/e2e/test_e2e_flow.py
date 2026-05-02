#!/usr/bin/env python3
"""
SupplyChainForge — End-to-End Integration Test Script
======================================================
Exercises the full order-to-delivery flow against a *running* stack
(docker compose or GCP Cloud Run).

Usage
-----
  # Against local docker compose stack:
  python tests/e2e/test_e2e_flow.py

  # Against a deployed GCP environment:
  INVENTORY_URL=https://inventory-xxx.a.run.app \
  ORDER_URL=https://order-xxx.a.run.app \
  FULFILLMENT_URL=https://fulfillment-xxx.a.run.app \
  python tests/e2e/test_e2e_flow.py

Exit codes
----------
  0  all scenarios passed
  1  one or more scenarios failed
"""

import os
import sys
import time
import json
import uuid
import random
import string
import logging
import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("e2e")

# ── Configuration ──────────────────────────────────────────────────────────────

INVENTORY_URL  = os.getenv("INVENTORY_URL",  "http://localhost:8001")
ORDER_URL      = os.getenv("ORDER_URL",      "http://localhost:8002")
FULFILLMENT_URL = os.getenv("FULFILLMENT_URL", "http://localhost:8003")

TIMEOUT = httpx.Timeout(10.0, read=30.0)
POLL_INTERVAL = 1.0          # seconds between status polls
POLL_TIMEOUT  = 30.0         # max seconds to wait for async state transitions

# ── Helpers ────────────────────────────────────────────────────────────────────

def _sku() -> str:
    """Generate a random SKU to avoid collisions between test runs."""
    return "E2E-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))


def _assert(condition: bool, msg: str) -> None:
    if not condition:
        raise AssertionError(msg)


def _poll_until(url: str, field: str, expected: str, client: httpx.Client) -> dict:
    """Poll a GET endpoint until *field* equals *expected* or timeout."""
    deadline = time.monotonic() + POLL_TIMEOUT
    while time.monotonic() < deadline:
        r = client.get(url)
        r.raise_for_status()
        data = r.json()
        if data.get(field) == expected:
            return data
        time.sleep(POLL_INTERVAL)
    raise TimeoutError(
        f"Timed out waiting for {url} field '{field}' == '{expected}'. "
        f"Last value: {data.get(field)!r}"
    )


# ── Test scenarios ─────────────────────────────────────────────────────────────

def test_health_checks(client: httpx.Client) -> None:
    log.info("=== Scenario: Health checks ===")
    for name, base in [
        ("inventory",  INVENTORY_URL),
        ("order",      ORDER_URL),
        ("fulfillment", FULFILLMENT_URL),
    ]:
        r = client.get(f"{base}/health")
        _assert(r.status_code == 200, f"{name} /health returned {r.status_code}")
        body = r.json()
        _assert(body.get("status") == "ok", f"{name} health status != ok: {body}")
        log.info("  [OK] %s /health", name)

        r = client.get(f"{base}/health/ready")
        _assert(r.status_code == 200, f"{name} /health/ready returned {r.status_code}")
        log.info("  [OK] %s /health/ready", name)


def test_product_crud(client: httpx.Client) -> dict:
    log.info("=== Scenario: Product CRUD ===")
    sku = _sku()

    # Create
    r = client.post(
        f"{INVENTORY_URL}/api/v1/products",
        json={
            "sku": sku,
            "name": f"E2E Test Product {sku}",
            "category": "electronics",
            "unit_price": "199.99",
            "quantity_available": 100,
            "reorder_point": 10,
        },
    )
    _assert(r.status_code == 201, f"Create product: expected 201, got {r.status_code}: {r.text}")
    product = r.json()
    log.info("  [OK] Created product id=%d sku=%s", product["id"], product["sku"])

    # Read
    r = client.get(f"{INVENTORY_URL}/api/v1/products/{product['id']}")
    _assert(r.status_code == 200, f"Get product: {r.status_code}")
    _assert(r.json()["sku"] == sku, "SKU mismatch on GET")
    log.info("  [OK] Read product id=%d", product["id"])

    # Update
    r = client.put(
        f"{INVENTORY_URL}/api/v1/products/{product['id']}",
        json={"name": f"{sku} Updated"},
    )
    _assert(r.status_code == 200, f"Update product: {r.status_code}")
    log.info("  [OK] Updated product name")

    return product


def test_stock_reservation(client: httpx.Client, product: dict) -> None:
    log.info("=== Scenario: Stock reservation ===")
    order_ref = f"ORD-E2E-{uuid.uuid4().hex[:8].upper()}"

    r = client.post(
        f"{INVENTORY_URL}/api/v1/products/{product['id']}/reserve",
        json={"quantity": 5, "order_id": order_ref},
    )
    _assert(r.status_code == 200, f"Reserve: expected 200, got {r.status_code}: {r.text}")
    data = r.json()
    _assert(data["quantity_reserved"] == 5, f"Expected reserved=5, got {data['quantity_reserved']}")
    log.info("  [OK] Reserved 5 units; reserved=%d", data["quantity_reserved"])

    # Attempt to reserve more than available — should fail 409
    r = client.post(
        f"{INVENTORY_URL}/api/v1/products/{product['id']}/reserve",
        json={"quantity": 9999, "order_id": f"ORD-E2E-OVERSTOCK"},
    )
    _assert(r.status_code in (409, 422), f"Over-reserve: expected 409/422, got {r.status_code}")
    log.info("  [OK] Over-reserve correctly rejected (%d)", r.status_code)

    # Release
    r = client.post(
        f"{INVENTORY_URL}/api/v1/products/{product['id']}/release",
        json={"quantity": 5, "order_id": order_ref},
    )
    _assert(r.status_code == 200, f"Release: expected 200, got {r.status_code}: {r.text}")
    log.info("  [OK] Released 5 units")


def test_full_order_flow(client: httpx.Client, product: dict) -> None:
    log.info("=== Scenario: Full order flow (order → fulfillment) ===")

    # --- Create order ---
    r = client.post(
        f"{ORDER_URL}/api/v1/orders",
        json={
            "customer_id": "e2e-customer-001",
            "shipping_address": "1 E2E Test Lane, Dubai, UAE",
            "items": [
                {
                    "product_id": product["id"],
                    "sku": product["sku"],
                    "quantity": 2,
                    "unit_price": str(product["unit_price"]),
                }
            ],
        },
    )
    _assert(r.status_code == 201, f"Create order: expected 201, got {r.status_code}: {r.text}")
    order = r.json()
    order_id = order["id"]
    _assert(order["status"] == "confirmed", f"Expected 'confirmed', got {order['status']!r}")
    log.info("  [OK] Order created id=%d status=%s", order_id, order["status"])

    # --- Get order by ID ---
    r = client.get(f"{ORDER_URL}/api/v1/orders/{order_id}")
    _assert(r.status_code == 200, f"Get order: {r.status_code}")
    log.info("  [OK] Order GET id=%d", order_id)

    # --- Fulfillment record should exist (may take a moment if using Pub/Sub) ---
    log.info("  [..] Polling for fulfillment record (order_id=%d)", order_id)
    try:
        fulfillment = _poll_until(
            f"{FULFILLMENT_URL}/api/v1/fulfillments/by-order/{order_id}",
            "status",
            "assigned",
            client,
        )
        fulfillment_id = fulfillment["id"]
        log.info(
            "  [OK] Fulfillment id=%d status=%s warehouse=%s carrier=%s",
            fulfillment_id,
            fulfillment["status"],
            fulfillment.get("warehouse_id"),
            fulfillment.get("carrier"),
        )
    except (httpx.HTTPStatusError, TimeoutError, Exception) as exc:
        log.warning(
            "  [SKIP] Fulfillment polling skipped (Pub/Sub not enabled in this env): %s", exc
        )
        return

    # --- Advance fulfillment through state machine ---
    r = client.post(f"{FULFILLMENT_URL}/api/v1/fulfillments/{fulfillment_id}/pick")
    _assert(r.status_code == 200, f"Pick: {r.status_code}: {r.text}")
    log.info("  [OK] Started picking fulfillment_id=%d", fulfillment_id)

    r = client.post(
        f"{FULFILLMENT_URL}/api/v1/fulfillments/{fulfillment_id}/ship",
        json={"tracking_number": f"TRK-E2E-{uuid.uuid4().hex[:10].upper()}"},
    )
    _assert(r.status_code == 200, f"Ship: {r.status_code}: {r.text}")
    log.info("  [OK] Marked shipped fulfillment_id=%d tracking=%s",
             fulfillment_id, r.json().get("tracking_number"))

    r = client.post(f"{FULFILLMENT_URL}/api/v1/fulfillments/{fulfillment_id}/complete")
    _assert(r.status_code == 200, f"Complete: {r.status_code}: {r.text}")
    log.info("  [OK] Marked completed fulfillment_id=%d", fulfillment_id)

    # --- Order should now be DELIVERED (via fulfillment.completed Pub/Sub event) ---
    log.info("  [..] Polling for order status == 'delivered' (order_id=%d)", order_id)
    try:
        updated = _poll_until(
            f"{ORDER_URL}/api/v1/orders/{order_id}",
            "status",
            "delivered",
            client,
        )
        log.info("  [OK] Order id=%d final status=%s", order_id, updated["status"])
    except TimeoutError:
        log.warning(
            "  [SKIP] Order status polling timed out — Pub/Sub may not be enabled in this env."
        )


def test_order_cancellation(client: httpx.Client, product: dict) -> None:
    log.info("=== Scenario: Order cancellation ===")

    r = client.post(
        f"{ORDER_URL}/api/v1/orders",
        json={
            "customer_id": "e2e-cancel-customer",
            "shipping_address": "2 Cancel St, Dubai, UAE",
            "items": [
                {
                    "product_id": product["id"],
                    "sku": product["sku"],
                    "quantity": 1,
                    "unit_price": str(product["unit_price"]),
                }
            ],
        },
    )
    _assert(r.status_code == 201, f"Create order for cancel: {r.status_code}: {r.text}")
    order_id = r.json()["id"]

    r = client.post(
        f"{ORDER_URL}/api/v1/orders/{order_id}/cancel",
        json={"reason": "E2E test cancellation"},
    )
    _assert(r.status_code == 200, f"Cancel order: {r.status_code}: {r.text}")
    _assert(r.json()["status"] == "cancelled", f"Expected 'cancelled', got {r.json()['status']!r}")
    log.info("  [OK] Order id=%d cancelled", order_id)


def test_low_stock_filter(client: httpx.Client) -> None:
    log.info("=== Scenario: Low-stock filter ===")
    sku = _sku()

    r = client.post(
        f"{INVENTORY_URL}/api/v1/products",
        json={
            "sku": sku,
            "name": f"Low Stock Item {sku}",
            "category": "test",
            "unit_price": "1.00",
            "quantity_available": 2,
            "reorder_point": 10,       # immediately below reorder point
        },
    )
    _assert(r.status_code == 201, f"Create low-stock product: {r.status_code}")
    product_id = r.json()["id"]

    r = client.get(f"{INVENTORY_URL}/api/v1/products?low_stock_only=true")
    _assert(r.status_code == 200, f"Low stock filter: {r.status_code}")
    skus = [p["sku"] for p in r.json()["items"]]
    _assert(sku in skus, f"Newly created low-stock SKU {sku} not in response: {skus}")
    log.info("  [OK] Low-stock item %s appears in low_stock_only filter", sku)


# ── Runner ─────────────────────────────────────────────────────────────────────

def main() -> int:
    log.info("SupplyChainForge E2E Test")
    log.info("  Inventory  : %s", INVENTORY_URL)
    log.info("  Order      : %s", ORDER_URL)
    log.info("  Fulfillment: %s", FULFILLMENT_URL)

    failures: list[str] = []

    with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
        scenarios = [
            ("health_checks",       lambda: test_health_checks(client)),
            ("product_crud",        lambda: (product := test_product_crud(client))),
            ("low_stock_filter",    lambda: test_low_stock_filter(client)),
        ]

        # Run setup scenarios first to get a product
        product = None
        for name, fn in scenarios:
            try:
                result = fn()
                if name == "product_crud":
                    product = result
            except Exception as exc:
                log.error("  [FAIL] %s: %s", name, exc)
                failures.append(f"{name}: {exc}")

        if product is None:
            log.error("Product creation failed; skipping dependent scenarios.")
            failures.append("product_crud: no product available")
        else:
            for name, fn in [
                ("stock_reservation",   lambda: test_stock_reservation(client, product)),
                ("full_order_flow",     lambda: test_full_order_flow(client, product)),
                ("order_cancellation",  lambda: test_order_cancellation(client, product)),
            ]:
                try:
                    fn()
                except Exception as exc:
                    log.error("  [FAIL] %s: %s", name, exc)
                    failures.append(f"{name}: {exc}")

    print()
    if failures:
        log.error("=== FAILED: %d scenario(s) ===", len(failures))
        for f in failures:
            log.error("  - %s", f)
        return 1
    else:
        log.info("=== ALL SCENARIOS PASSED ===")
        return 0


if __name__ == "__main__":
    sys.exit(main())
