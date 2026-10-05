"""
Google OAuth 2.0 authorization-code flow, server side.

Used twice: once for sign-in (``openid email profile``) and once, separately,
to connect Gmail (adds ``gmail.readonly`` with offline access). Keeping them
apart means signing in never asks for mailbox access, and a user can use the
tracker without connecting Gmail at all.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from src.core.config import get_settings

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"

SIGN_IN_SCOPES = ["openid", "email", "profile"]
GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
# openid + email identify which mailbox was granted, which may not be the
# account the user signed in with.
GMAIL_CONNECT_SCOPES = ["openid", "email", GMAIL_SCOPE]


class OAuthError(RuntimeError):
    """The OAuth exchange failed or returned something unusable."""


@dataclass(frozen=True)
class GoogleIdentity:
    sub: str
    email: str
    name: str | None
    picture: str | None


@dataclass(frozen=True)
class TokenGrant:
    identity: GoogleIdentity
    scopes: frozenset[str]
    refresh_token: str | None


def redirect_uri(purpose: str) -> str:
    """Callback URL for ``purpose`` ('auth' or 'gmail')."""
    return f"{get_settings().public_url}/api/{purpose}/callback"


def authorization_url(
    purpose: str, scopes: list[str], state: str, login_hint: str | None = None
) -> str:
    settings = get_settings()
    if not settings.GOOGLE_OAUTH_CLIENT_ID or not settings.GOOGLE_OAUTH_CLIENT_SECRET:
        raise OAuthError("Google OAuth client is not configured.")
    params = {
        "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
        "redirect_uri": redirect_uri(purpose),
        "response_type": "code",
        "scope": " ".join(scopes),
        "state": state,
    }
    if GMAIL_SCOPE in scopes:
        # A refresh token is only issued with offline access, and Google only
        # re-issues one on an explicit consent screen. Without prompt=consent a
        # user reconnecting after a disconnect would get no refresh token.
        params["access_type"] = "offline"
        params["prompt"] = "consent"
    else:
        params["prompt"] = "select_account"
    if login_hint:
        params["login_hint"] = login_hint
    return f"{AUTH_URL}?{urlencode(params)}"


async def exchange_code(purpose: str, code: str) -> TokenGrant:
    """Exchange an authorization code and verify the returned identity."""
    settings = get_settings()
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
                "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
                "redirect_uri": redirect_uri(purpose),
                "grant_type": "authorization_code",
            },
        )
    if response.status_code != 200:
        raise OAuthError(f"Token exchange failed ({response.status_code}).")
    body = response.json()
    raw_id_token = body.get("id_token")
    if not raw_id_token:
        raise OAuthError("Google returned no ID token.")

    # Verifying the signature is not strictly needed for a token received
    # directly from Google over TLS, but it also enforces audience and expiry.
    try:
        claims = await asyncio.to_thread(
            id_token.verify_oauth2_token,
            raw_id_token,
            google_requests.Request(),
            settings.GOOGLE_OAUTH_CLIENT_ID,
        )
    except ValueError as exc:
        raise OAuthError("Google ID token failed verification.") from exc

    if not claims.get("email") or not claims.get("email_verified"):
        raise OAuthError("Google account has no verified email address.")

    return TokenGrant(
        identity=GoogleIdentity(
            sub=claims["sub"],
            email=claims["email"].lower(),
            name=claims.get("name"),
            picture=claims.get("picture"),
        ),
        # Users can untick individual scopes on Google's consent screen, so
        # the grant has to be checked rather than assumed.
        scopes=frozenset(body.get("scope", "").split()),
        refresh_token=body.get("refresh_token"),
    )


async def revoke_token(token: str) -> None:
    """Best-effort revocation; a token already revoked is not an error."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        await client.post(REVOKE_URL, data={"token": token})
