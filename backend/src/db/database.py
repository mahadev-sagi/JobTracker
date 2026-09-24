"""
Async database connection pool backed by *asyncpg*.

Usage::

    from src.db.database import init_pool, close_pool, get_connection

    # At application startup
    await init_pool()

    # In a request handler
    async with get_connection() as conn:
        rows = await conn.fetch("SELECT * FROM applications")

    # At application shutdown
    await close_pool()
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg

from src.core.config import get_settings

logger = logging.getLogger(__name__)

# Module-level pool reference ------------------------------------------------
_pool: asyncpg.Pool | None = None


async def init_pool() -> asyncpg.Pool:
    """Create (or return the existing) connection pool.

    Pool size defaults are tuned for a small-to-medium workload behind
    uvicorn with 2 workers.
    """
    global _pool  # noqa: PLW0603
    if _pool is not None:
        return _pool

    settings = get_settings()
    logger.info("Initializing asyncpg connection pool …")

    _pool = await asyncpg.create_pool(
        dsn=settings.DATABASE_URL,
        min_size=2,
        max_size=10,
        max_inactive_connection_lifetime=300.0,
        command_timeout=30.0,
    )
    logger.info("Connection pool ready (min=2, max=10)")
    return _pool


async def close_pool() -> None:
    """Gracefully close the connection pool."""
    global _pool  # noqa: PLW0603
    if _pool is not None:
        logger.info("Closing asyncpg connection pool …")
        await _pool.close()
        _pool = None
        logger.info("Connection pool closed")


def get_pool() -> asyncpg.Pool:
    """Return the initialised pool or raise if it hasn't been created yet."""
    if _pool is None:
        raise RuntimeError(
            "Database pool is not initialised. Call init_pool() first."
        )
    return _pool


@asynccontextmanager
async def get_connection() -> AsyncIterator[asyncpg.Connection]:
    """Acquire a connection from the pool and release it when done.

    Yields
    ------
    asyncpg.Connection
        A connection that is automatically returned to the pool on exit.
    """
    pool = get_pool()
    conn: asyncpg.Connection = await pool.acquire()
    try:
        yield conn
    finally:
        await pool.release(conn)
