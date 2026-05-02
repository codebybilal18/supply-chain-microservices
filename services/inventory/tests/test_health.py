"""
Health endpoint tests.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_liveness(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "alive"
    assert body["service"] == "inventory-service"
    assert "version" in body


@pytest.mark.asyncio
async def test_readiness_with_db(client: AsyncClient) -> None:
    """Readiness should be 'ready' when the DB session is injected."""
    response = await client.get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["dependencies"]["database"] == "connected"
