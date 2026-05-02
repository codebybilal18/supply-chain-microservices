"""
Order Service test configuration.

Uses in-memory SQLite + respx to mock Inventory Service HTTP calls.
"""

import asyncio
import pytest
import pytest_asyncio
from decimal import Decimal
from typing import AsyncGenerator

import respx
import httpx
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.dependencies import get_db
from app.main import app as _app


# ── Async event loop ──────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def event_loop_policy():
    return asyncio.DefaultEventLoopPolicy()


# ── SQLite in-memory DB per test ───────────────────────────────────────────────

@pytest_asyncio.fixture()
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


# ── FastAPI test client with DB override ──────────────────────────────────────

@pytest_asyncio.fixture()
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    async def override_get_db():
        yield db_session

    _app.dependency_overrides[get_db] = override_get_db
    # Disable pubsub
    _app.state.pubsub_publisher = None

    async with AsyncClient(
        transport=ASGITransport(app=_app), base_url="http://test"
    ) as ac:
        yield ac

    _app.dependency_overrides.clear()


# ── Inventory mock ────────────────────────────────────────────────────────────

INVENTORY_BASE = "http://inventory:8000"


@pytest.fixture()
def mock_inventory():
    """
    Returns a respx.MockRouter pre-configured with default happy-path responses.
    Tests can override individual routes with additional mock calls.
    """
    with respx.mock(base_url=INVENTORY_BASE, assert_all_mocked=False, assert_all_called=False) as mock:
        # Default: product exists with plenty of stock
        mock.get("/api/v1/products/1").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 1,
                    "sku": "SKU-001",
                    "name": "Widget A",
                    "quantity_on_hand": 100,
                    "price": "9.99",
                },
            )
        )
        mock.post("/api/v1/products/1/reserve").mock(
            return_value=httpx.Response(200, json={"reserved": True})
        )
        mock.post("/api/v1/products/1/release").mock(
            return_value=httpx.Response(200, json={"released": True})
        )
        mock.get("/api/v1/products/2").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 2,
                    "sku": "SKU-002",
                    "name": "Gadget B",
                    "quantity_on_hand": 50,
                    "price": "29.99",
                },
            )
        )
        mock.post("/api/v1/products/2/reserve").mock(
            return_value=httpx.Response(200, json={"reserved": True})
        )
        yield mock
