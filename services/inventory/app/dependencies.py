"""
FastAPI dependency providers.

`get_db` is the primary dependency injected into every route handler.
It manages the async session lifecycle: yields the session, commits on
success, and rolls back on any unhandled exception.

`get_cache` provides the CacheService singleton (set on app state at startup).
"""

from collections.abc import AsyncGenerator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Yield an AsyncSession for a single request.

    The session is committed automatically on success and rolled back on
    any exception, then closed/returned to the pool in the finally block.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def get_cache(request: Request):
    """Return the CacheService instance stored on app.state at startup, or None."""
    return getattr(request.app.state, "cache", None)
