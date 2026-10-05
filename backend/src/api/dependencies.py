"""
FastAPI dependency functions.

Dependencies are injected into route handlers via ``Depends()``.
"""

from __future__ import annotations

import hmac
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID

import asyncpg
from fastapi import Cookie, Depends, Header, HTTPException, status
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from src.core.config import Settings, get_settings
from src.core.security import hash_token
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


# ── Signed-in user ──────────────────────────────────────────────────────
SESSION_COOKIE = "jt_session"


@dataclass(frozen=True)
class CurrentUser:
    id: UUID
    email: str
    name: str | None
    picture_url: str | None
    is_admin: bool


async def get_current_user(
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    conn: asyncpg.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> CurrentUser:
    """Resolve the session cookie to a user, or fail with 401."""
    if not session_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in.")
    row = await conn.fetchrow(
        """
        SELECT u.id, u.email, u.name, u.picture_url
        FROM sessions s JOIN users u ON u.id = s.user_id
        WHERE s.token_hash = $1 AND s.expires_at > NOW()
        """,
        hash_token(session_token),
    )
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired.")
    # Re-checked on every request so removing someone from ALLOWED_EMAILS
    # takes effect immediately, not when their session lapses.
    if not settings.may_sign_in(row["email"]):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Access has been withdrawn.")
    return CurrentUser(
        id=row["id"],
        email=row["email"],
        name=row["name"],
        picture_url=row["picture_url"],
        is_admin=row["email"].lower() in settings.admin_emails,
    )


async def require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admins only.")
    return user


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

    If neither is configured the request is refused in every environment,
    since development servers can also be exposed through a tunnel.

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
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook authentication is not configured.",
        )

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
