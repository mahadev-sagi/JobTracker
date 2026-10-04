"""
Gmail API integration service.

Provides async helpers to authenticate with the Gmail API, fetch new
messages via history-based sync, read message content, and set up
push notifications via Google Cloud Pub/Sub.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import re
from email.utils import parseaddr
from html import unescape
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from src.core.config import get_settings

logger = logging.getLogger(__name__)


class GmailAuthError(RuntimeError):
    """Raised when Gmail credentials are missing, invalid or unrefreshable."""

_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
]

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\n{3,}")


def _strip_html(html: str) -> str:
    """Naïvely convert HTML to plain text."""
    text = _HTML_TAG_RE.sub("", html)
    text = unescape(text)
    text = _WHITESPACE_RE.sub("\n\n", text)
    return text.strip()


class GmailService:
    """
    Thin async-friendly wrapper around the synchronous
    ``googleapiclient`` Gmail resource.

    All public methods are ``async`` so callers can use
    ``asyncio.to_thread`` internally if needed; currently the
    underlying client is blocking so each call is executed in the
    default thread-pool via ``asyncio.to_thread``.
    """

    def __init__(self, credentials_path: str | None = None) -> None:
        """
        Build and authenticate the Gmail API client.

        Parameters
        ----------
        credentials_path:
            Path to a previously authorised ``token.json``. Defaults to
            ``settings.GOOGLE_CREDENTIALS_JSON``.
        """
        settings = get_settings()
        self._credentials_path = credentials_path or settings.GOOGLE_CREDENTIALS_JSON
        if not self._credentials_path:
            raise GmailAuthError(
                "No Gmail credentials configured. Set GOOGLE_CREDENTIALS_JSON "
                "to the path of an authorised token.json."
            )
        self._creds: Credentials | None = None
        self._service: Any = None
        self._authenticate()

    # ── Private helpers ──────────────────────────────────────────────

    def _authenticate(self) -> None:
        """Load and refresh stored OAuth credentials.

        Deliberately never starts an interactive consent flow. The server runs
        headless in Docker and Lambda, where ``run_local_server`` would block
        forever on a browser that cannot open. Minting the token is a one-time
        operation performed out of band by
        ``backend/scripts/bootstrap_gmail_token.py``.
        """
        token_path = self._credentials_path

        if not os.path.exists(token_path):
            raise GmailAuthError(
                f"Gmail token not found at '{token_path}'. Run "
                "`python backend/scripts/bootstrap_gmail_token.py` once on a "
                "machine with a browser, then mount the resulting token.json."
            )

        try:
            self._creds = Credentials.from_authorized_user_file(token_path, _SCOPES)
        except ValueError as exc:
            raise GmailAuthError(
                f"'{token_path}' is not a valid authorised-user token file. "
                "It should be the token.json produced by the bootstrap "
                "script, not the OAuth client credentials.json."
            ) from exc

        if not self._creds.valid:
            if self._creds.expired and self._creds.refresh_token:
                logger.info("Gmail credentials expired — refreshing.")
                self._creds.refresh(Request())
                # Persist the rotated access token so a restart does not need
                # to refresh again. Best-effort: the path may be mounted
                # read-only, which is not fatal.
                try:
                    with open(token_path, "w") as f:
                        f.write(self._creds.to_json())
                except OSError:
                    logger.warning(
                        "Could not write refreshed token back to %s", token_path
                    )
            else:
                raise GmailAuthError(
                    "Stored Gmail credentials are invalid and cannot be "
                    "refreshed (no refresh_token). Re-run the bootstrap script."
                )

        self._service = build("gmail", "v1", credentials=self._creds)

    def _users(self) -> Any:
        """Shortcut for ``service.users()``."""
        return self._service.users()

    # ── Public API ───────────────────────────────────────────────────

    async def get_new_messages(self, history_id: str) -> list[dict]:
        """
        Fetch message stubs added since *history_id*.

        Returns a list of dicts each containing at least an ``"id"`` key.
        Returns an empty list when no new history is available (e.g.
        when ``historyId`` is already up-to-date).
        """

        def _fetch() -> list[dict]:
            results: list[dict] = []
            request = self._users().history().list(
                userId="me",
                startHistoryId=history_id,
                historyTypes=["messageAdded"],
            )
            while request is not None:
                response = request.execute()
                for record in response.get("history", []):
                    for msg in record.get("messagesAdded", []):
                        results.append(msg["message"])
                request = self._users().history().list_next(request, response)
            return results

        try:
            return await asyncio.to_thread(_fetch)
        except Exception:
            logger.exception("Failed to fetch history since %s", history_id)
            raise

    async def get_message_content(
        self,
        message_id: str,
    ) -> tuple[str, str, str]:
        """
        Retrieve the subject, plain-text body, and sender of a message.

        Returns
        -------
        tuple[str, str, str]
            ``(subject, body, sender)``
        """

        def _fetch() -> tuple[str, str, str]:
            msg = (
                self._users()
                .messages()
                .get(userId="me", id=message_id, format="full")
                .execute()
            )

            headers = {
                h["name"].lower(): h["value"]
                for h in msg.get("payload", {}).get("headers", [])
            }
            subject = headers.get("subject", "(no subject)")
            sender = headers.get("from", "")
            _, sender_email = parseaddr(sender)
            sender_display = sender if sender_email else sender

            body = self._extract_body(msg.get("payload", {}))
            return subject, body, sender_display

        return await asyncio.to_thread(_fetch)

    async def setup_watch(self, topic_name: str) -> dict:
        """
        Register a Gmail push-notification watch on the user's inbox.

        Parameters
        ----------
        topic_name:
            Fully-qualified Cloud Pub/Sub topic, e.g.
            ``projects/my-project/topics/gmail-push``.

        Returns
        -------
        dict
            The watch response containing ``historyId`` and ``expiration``.
        """

        def _watch() -> dict:
            body = {
                "topicName": topic_name,
                "labelIds": ["INBOX"],
            }
            return self._users().watch(userId="me", body=body).execute()

        result = await asyncio.to_thread(_watch)
        logger.info(
            "Gmail watch registered — historyId=%s, expiration=%s",
            result.get("historyId"),
            result.get("expiration"),
        )
        return result

    # ── Body extraction ──────────────────────────────────────────────

    @staticmethod
    def _extract_body(payload: dict) -> str:
        """
        Walk the MIME tree and return the best plain-text body.

        Prefers ``text/plain``; falls back to ``text/html`` (stripped).
        """
        parts = payload.get("parts", [])
        if not parts:
            # Single-part message
            mime = payload.get("mimeType", "")
            data = payload.get("body", {}).get("data", "")
            decoded = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            return _strip_html(decoded) if "html" in mime else decoded

        plain: str | None = None
        html: str | None = None

        for part in parts:
            mime = part.get("mimeType", "")
            data = part.get("body", {}).get("data", "")
            if not data:
                # Recurse into nested multipart
                nested = GmailService._extract_body(part)
                if nested:
                    if mime == "text/plain" and plain is None:
                        plain = nested
                    elif "html" in mime and html is None:
                        html = nested
                continue

            decoded = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            if mime == "text/plain" and plain is None:
                plain = decoded
            elif "html" in mime and html is None:
                html = decoded

        if plain:
            return plain
        if html:
            return _strip_html(html)
        return ""


# ---------------------------------------------------------------------------
# Module-level accessor
# ---------------------------------------------------------------------------

_service_singleton: GmailService | None = None


def get_gmail_service() -> GmailService:
    """Return a lazily built, process-wide ``GmailService``.

    Authentication reads a token from disk and builds an HTTP client, so
    constructing one per inbound webhook would be wasteful. The instance
    refreshes its own credentials as they expire.
    """
    global _service_singleton  # noqa: PLW0603
    if _service_singleton is None:
        _service_singleton = GmailService()
    return _service_singleton


def reset_gmail_service() -> None:
    """Drop the cached instance. Used by tests and after a token rotation."""
    global _service_singleton  # noqa: PLW0603
    _service_singleton = None
