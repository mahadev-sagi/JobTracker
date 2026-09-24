"""
FastAPI dependency functions.

Dependencies are injected into route handlers via ``Depends()``.
"""

from __future__ import annotations

import hmac
import logging
from collections.abc import AsyncIterator

import asyncpg
from fastapi import Depends, Header, HTTPException, status

from src.core.config import Settings, get_settings
from src.db.database import get_pool

logger = logging.getLogger(__name__)


# ── Database connection dependency ──────────────────────────────────────
async def get_db() -> AsyncIterator[asyncpg.Connection]:
    """Yield a database connection from the pool, then release it.

    Usage in a route::

        @router.get("/items")
        async def list_items(conn: asyncpg.Connection = Depends(get_db)):
            ...
    """
    pool = get_pool()
    conn: asyncpg.Connection = await pool.acquire()
    try:
        yield conn
    finally:
        await pool.release(conn)


# ── Pub/Sub push-endpoint auth dependency ───────────────────────────────
async def verify_pubsub_token(
    authorization: str | None = Header(default=None, alias="Authorization"),
    settings: Settings = Depends(get_settings),
) -> bool:
    """Verify the bearer token attached to Google Cloud Pub/Sub push requests.

    Google Pub/Sub push subscriptions can be configured with an
    *authentication token* that is sent as a Bearer token in the
    ``Authorization`` header.  This dependency validates that token
    against the value stored in ``GOOGLE_PUBSUB_SUBSCRIPTION`` (used
    here as a shared secret for simplicity; swap for proper OIDC
    verification in production).

    Raises
    ------
    HTTPException 401
        If the header is missing or the token doesn't match.
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
        )

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization scheme – expected 'Bearer <token>'",
        )

    # Constant-time comparison to prevent timing attacks
    expected = settings.GOOGLE_PUBSUB_SUBSCRIPTION
    if not hmac.compare_digest(token, expected):
        logger.warning("Pub/Sub token mismatch – rejecting webhook request")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Pub/Sub token",
        )

    return True
