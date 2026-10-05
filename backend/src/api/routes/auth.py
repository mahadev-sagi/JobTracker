"""
Sign-in with Google, sessions, and the current-user endpoint.
"""

from __future__ import annotations

import hmac
import logging
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from asyncpg import Connection
from asyncpg.exceptions import UniqueViolationError
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from src.api.dependencies import (
    SESSION_COOKIE,
    CurrentUser,
    get_current_user,
    get_db,
)
from src.core import google_oauth
from src.core.config import Settings, get_settings
from src.core.security import hash_token, new_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["Auth"])


# ---------------------------------------------------------------------------
# OAuth state, shared with the Gmail connect flow
# ---------------------------------------------------------------------------

def _state_cookie(purpose: str) -> str:
    return f"jt_oauth_{purpose}"


def start_oauth(
    purpose: str, scopes: list[str], login_hint: str | None = None
) -> RedirectResponse:
    """Redirect to Google's consent screen, binding the request to this browser.

    The random ``state`` is echoed back by Google and must match the cookie
    set here; otherwise anyone could complete a flow they started in someone
    else's browser (login CSRF, or attaching their mailbox to your account).
    """
    settings = get_settings()
    state = new_token()
    try:
        url = google_oauth.authorization_url(purpose, scopes, state, login_hint)
    except google_oauth.OAuthError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    response = RedirectResponse(url, status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        _state_cookie(purpose),
        state,
        max_age=600,
        path=f"/api/{purpose}",
        httponly=True,
        secure=settings.secure_cookies,
        # Lax still sends the cookie on Google's top-level redirect back.
        samesite="lax",
    )
    return response


def check_oauth_state(request: Request, purpose: str, state: str | None) -> bool:
    expected = request.cookies.get(_state_cookie(purpose))
    return bool(expected and state and hmac.compare_digest(expected, state))


def finish_redirect(path: str, purpose: str, **params: str) -> RedirectResponse:
    """Redirect back into the app and drop the spent state cookie."""
    query = f"?{urlencode(params)}" if params else ""
    response = RedirectResponse(f"{path}{query}", status_code=status.HTTP_302_FOUND)
    response.delete_cookie(_state_cookie(purpose), path=f"/api/{purpose}")
    return response


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

async def _create_session(
    conn: Connection, response: Response, user_id, settings: Settings
) -> None:
    token = new_token()
    ttl = timedelta(days=settings.SESSION_TTL_DAYS)
    await conn.execute(
        "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES ($1, $2, $3)",
        hash_token(token),
        user_id,
        datetime.now(UTC) + ttl,
    )
    # Opportunistic cleanup; there is no other job that would do it.
    await conn.execute("DELETE FROM sessions WHERE expires_at < NOW()")
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(ttl.total_seconds()),
        path="/",
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
    )


async def _upsert_user(conn: Connection, identity: google_oauth.GoogleIdentity):
    return await conn.fetchval(
        """
        INSERT INTO users (google_sub, email, name, picture_url)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (google_sub) DO UPDATE
        SET email = EXCLUDED.email,
            name = EXCLUDED.name,
            picture_url = EXCLUDED.picture_url,
            last_login_at = NOW()
        RETURNING id
        """,
        identity.sub,
        identity.email,
        identity.name,
        identity.picture,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/config")
async def auth_config(settings: Settings = Depends(get_settings)):
    """What the sign-in page should offer. Public."""
    return {
        "google": bool(settings.GOOGLE_OAUTH_CLIENT_ID),
        "dev_login": settings.dev_login_enabled,
    }


@router.get("/login")
async def login():
    """Start sign-in with Google."""
    return start_oauth("auth", google_oauth.SIGN_IN_SCOPES)


@router.get("/callback")
async def login_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    conn: Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Google redirects here after the consent screen."""
    if error:
        # The user cancelled, or Google refused (e.g. not a test user).
        return finish_redirect("/login", "auth", error="cancelled")
    if not code or not check_oauth_state(request, "auth", state):
        return finish_redirect("/login", "auth", error="state")

    try:
        grant = await google_oauth.exchange_code("auth", code)
    except google_oauth.OAuthError:
        logger.exception("Sign-in token exchange failed")
        return finish_redirect("/login", "auth", error="google")

    if not settings.may_sign_in(grant.identity.email):
        logger.info("Refused sign-in for %s (not invited)", grant.identity.email)
        return finish_redirect("/login", "auth", error="not_invited")

    response = finish_redirect("/", "auth")
    try:
        async with conn.transaction():
            user_id = await _upsert_user(conn, grant.identity)
            await _create_session(conn, response, user_id, settings)
    except UniqueViolationError:
        # The address belongs to an existing user with a different Google
        # account id (e.g. a deleted and recreated Google account). Merging
        # automatically would hand that user's data to whoever now holds the
        # address, so refuse and leave it to the admin.
        logger.warning("Refused sign-in for %s: email bound to another account", grant.identity.email)
        return finish_redirect("/login", "auth", error="account_conflict")
    logger.info("User %s signed in", grant.identity.email)
    return response


class DevLoginPayload(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+$")


@router.post("/dev-login", include_in_schema=False)
async def dev_login(
    payload: DevLoginPayload,
    response: Response,
    conn: Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Sign in as any address without Google. Development only."""
    if not settings.dev_login_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    email = payload.email.lower()
    if not settings.may_sign_in(email):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "That address is not invited.")
    async with conn.transaction():
        # Reuse an existing account with this address, whatever its Google
        # id, so dev sign-in can act as any real user of a copied database.
        user_id = await conn.fetchval("SELECT id FROM users WHERE email = $1", email)
        if user_id is None:
            identity = google_oauth.GoogleIdentity(
                sub=f"dev:{email}", email=email, name=email.split("@")[0], picture=None
            )
            user_id = await _upsert_user(conn, identity)
        await _create_session(conn, response, user_id, settings)
    return {"status": "ok"}


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, conn: Connection = Depends(get_db)):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        await conn.execute("DELETE FROM sessions WHERE token_hash = $1", hash_token(token))
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.get("/me")
async def me(
    user: CurrentUser = Depends(get_current_user),
    conn: Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """The signed-in user and the state of their Gmail connection."""
    gmail = await conn.fetchrow(
        """
        SELECT email_address, status, last_synced_at, watch_expires_at, last_error
        FROM gmail_accounts WHERE user_id = $1
        """,
        user.id,
    )
    return {
        "id": str(user.id),
        "email": user.email,
        "name": user.name,
        "picture_url": user.picture_url,
        "is_admin": user.is_admin,
        "gmail": dict(gmail) if gmail else None,
        # Lets the UI explain why "Connect Gmail" would not work yet.
        "gmail_available": bool(
            settings.GOOGLE_OAUTH_CLIENT_ID and settings.TOKEN_ENCRYPTION_KEY
        ),
    }
