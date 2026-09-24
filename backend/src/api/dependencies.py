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
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

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
    """Authenticate a Google Cloud Pub/Sub push request.

    This endpoint writes to the database on the strength of its payload, so it
    must not be open to the internet. Two modes, in order of preference:

    1. **OIDC** (set ``PUBSUB_AUDIENCE``) — the subscription is configured to
       attach a Google-signed identity token, which is verified here against
       Google's public keys. This is the correct production setup.
    2. **Shared secret** (set ``PUBSUB_VERIFICATION_TOKEN``) — a constant
       bearer string, adequate for local development over a tunnel.

    If neither is configured the request is refused in production, and allowed
    with a loud warning in development so the pipeline can be exercised
    locally without ceremony.

    Raises
    ------
    HTTPException 401
        If the header is missing, malformed, or fails verification.
    HTTPException 500
        If no verification method is configured in production.
    """
    oidc_mode = bool(settings.PUBSUB_AUDIENCE)
    secret_mode = bool(settings.PUBSUB_VERIFICATION_TOKEN)

    if not oidc_mode and not secret_mode:
        if settings.is_production:
            logger.error(
                "Gmail webhook is unauthenticated: set PUBSUB_AUDIENCE or "
                "PUBSUB_VERIFICATION_TOKEN."
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Webhook authentication is not configured.",
            )
        logger.warning(
            "Gmail webhook accepted WITHOUT authentication — development only. "
            "Set PUBSUB_AUDIENCE (preferred) or PUBSUB_VERIFICATION_TOKEN."
        )
        return True

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

    if oidc_mode:
        return _verify_oidc_token(token, settings)

    # Constant-time comparison to prevent timing attacks.
    if not hmac.compare_digest(token, settings.PUBSUB_VERIFICATION_TOKEN):
        logger.warning("Pub/Sub token mismatch – rejecting webhook request")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Pub/Sub token",
        )

    return True


def _verify_oidc_token(token: str, settings: Settings) -> bool:
    """Validate a Google-issued OIDC identity token from a push subscription.

    ``verify_oauth2_token`` checks the signature against Google's rotating
    public keys and enforces the issuer, audience and expiry.
    """
    try:
        claims = id_token.verify_oauth2_token(
            token,
            google_requests.Request(),
            audience=settings.PUBSUB_AUDIENCE,
        )
    except ValueError as exc:
        logger.warning("Rejecting Pub/Sub push with invalid OIDC token: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid OIDC token",
        ) from exc

    expected_sa = settings.PUBSUB_SERVICE_ACCOUNT_EMAIL
    if expected_sa and claims.get("email") != expected_sa:
        logger.warning(
            "OIDC token is valid but was issued to '%s', not '%s'.",
            claims.get("email"),
            expected_sa,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="OIDC token issued to an unexpected service account",
        )

    return True
