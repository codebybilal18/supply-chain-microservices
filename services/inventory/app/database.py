"""
Database engine and session factory.

Design decisions:
  - Async engine (aiomysql) for non-blocking I/O under FastAPI's event loop.
  - pool_pre_ping=True  → SQLAlchemy sends "SELECT 1" before each checkout,
    discarding stale connections silently (handles Cloud SQL proxy restarts).
  - pool_recycle        → prevents MySQL "server has gone away" errors after
    the server-side wait_timeout (default 8 h, we recycle at 30 min).
  - expire_on_commit=False in session factory → objects remain accessible
    after commit without an extra SELECT (important for async routes).
"""

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

# ── Engine ────────────────────────────────────────────────────────────────────
engine = create_async_engine(
    settings.database_url,
    echo=settings.DEBUG,          # log SQL in DEBUG mode only
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_timeout=settings.DB_POOL_TIMEOUT,
    pool_recycle=settings.DB_POOL_RECYCLE,
    pool_pre_ping=True,           # detect stale connections before use
)

# ── Session factory ───────────────────────────────────────────────────────────
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,              # we flush explicitly in service methods
    autocommit=False,
)


# ── Base class for all ORM models ─────────────────────────────────────────────
class Base(DeclarativeBase):
    """All SQLAlchemy ORM models inherit from this."""
    pass
