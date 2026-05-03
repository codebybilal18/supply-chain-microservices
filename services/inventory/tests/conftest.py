"""
Shared test fixtures.

Strategy:
  - Unit tests use an in-memory SQLite database (aiosqlite).
    This is fast and requires no external services.
  - Integration tests (Phase 2) will use a real MySQL container via
    pytest-docker or testcontainers-python.
  - Each test function gets a fresh DB session wrapped in a transaction
    that is rolled back after the test — no cross-test contamination.

SQLite notes:
  - SQLite does not support SELECT ... FOR UPDATE; the relevant service
    methods fall back to normal SELECTs in tests.  This is acceptable
    for unit-level tests; concurrency is tested in integration tests.
  - MySQL-specific column options (charset, collation) are stripped by
    SQLAlchemy when targeting SQLite.
"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.dependencies import get_db
from app.main import app

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(scope="function")
async def db_session() -> AsyncSession:
    """
    Yield a fresh AsyncSession backed by an in-memory SQLite DB.
    Schema is created before the test and the engine disposed after.
    """
    engine = create_async_engine(TEST_DB_URL, echo=False)

    async with engine.begin() as conn:
        # Create all tables defined in Base.metadata
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    async with factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def client(db_session: AsyncSession) -> AsyncClient:
    """
    Yield an AsyncClient wired to the FastAPI app with the test DB injected.
    The `get_db` dependency is overridden so no real MySQL connection is needed.
    """

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


# ── Sample data helpers ───────────────────────────────────────────────────────

SAMPLE_PRODUCT = {
    "sku": "CAT-ELEC-001",
    "name": "Samsung 65 QLED TV",
    "description": "4K QLED smart TV with Tizen OS",
    "category": "electronics",
    "unit_price": "1999.99",
    "quantity_available": 50,
    "reorder_point": 10,
}


def make_product(**overrides) -> dict:
    """Return a valid ProductCreate payload with optional field overrides."""
    return {**SAMPLE_PRODUCT, **overrides}
