"""Health endpoint tests."""

import pytest


@pytest.mark.asyncio
async def test_liveness(client):
    r = await client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "alive"
    assert data["service"] == "order-service"


@pytest.mark.asyncio
async def test_readiness(client):
    r = await client.get("/health/ready")
    assert r.status_code == 200
    data = r.json()
    assert data["dependencies"]["database"] == "connected"
