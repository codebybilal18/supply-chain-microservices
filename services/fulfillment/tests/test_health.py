"""Fulfillment health endpoint tests."""

import pytest


@pytest.mark.asyncio
async def test_liveness(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "alive"
    assert r.json()["service"] == "fulfillment-service"


@pytest.mark.asyncio
async def test_readiness(client):
    r = await client.get("/health/ready")
    assert r.status_code == 200
    assert r.json()["dependencies"]["database"] == "connected"
