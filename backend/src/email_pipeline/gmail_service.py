"""
Gmail API integration service.

One instance per connected mailbox, built from that user's stored refresh
token. Provides history-based incremental sync, a date-based fallback for
when Gmail has discarded the history, message reading, and watch management.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
from email.utils import parseaddr
from html import unescape
from typing import Any

from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from src.core.config import get_settings
from src.core.google_oauth import GMAIL_SCOPE, TOKEN_URL

logger = logging.getLogger(__name__)


class GmailAuthError(RuntimeError):
    """The user's grant is revoked or expired; they must reconnect Gmail."""


class HistoryExpiredError(RuntimeError):
    """Gmail no longer has history from the requested start id.

    Gmail keeps history for roughly a week. A mailbox that has not synced for
    longer (server down, watch lapsed) gets a 404 from history.list and must
    be recovered another way.
    """


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
    Async wrapper around the blocking ``googleapiclient`` Gmail resource.

    Every call runs in the default thread pool via ``asyncio.to_thread``.
    Access tokens are refreshed by google-auth on demand; a refresh that
    fails because the user revoked access surfaces as ``GmailAuthError``.
    """

    def __init__(self, refresh_token: str) -> None:
        settings = get_settings()
        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri=TOKEN_URL,
            client_id=settings.GOOGLE_OAUTH_CLIENT_ID,
            client_secret=settings.GOOGLE_OAUTH_CLIENT_SECRET,
            scopes=[GMAIL_SCOPE],
        )
        # cache_discovery=False: the file cache it would use is unavailable
        # and only produces a warning per build.
        self._service = build("gmail", "v1", credentials=creds, cache_discovery=False)

    def _users(self) -> Any:
        return self._service.users()

    async def _run(self, fn):
        try:
            return await asyncio.to_thread(fn)
        except RefreshError as exc:
            raise GmailAuthError(str(exc)) from exc

    # ── Sync ─────────────────────────────────────────────────────────

    async def get_new_messages(self, history_id: str) -> tuple[list[dict], str]:
        """
        Fetch inbox message stubs added since *history_id*.

        Returns ``(stubs, latest_history_id)``, where the latter is the
        mailbox's history id as of this call — the correct value to resume
        from next time, since every change up to it has now been seen.
        """

        def _fetch() -> tuple[list[dict], str]:
            results: list[dict] = []
            latest = history_id
            request = self._users().history().list(
                userId="me",
                startHistoryId=history_id,
                historyTypes=["messageAdded"],
                # Without this, sent mail and drafts are classified too.
                labelId="INBOX",
            )
            while request is not None:
                try:
                    response = request.execute()
                except HttpError as exc:
                    if exc.resp.status == 404:
                        raise HistoryExpiredError(history_id) from exc
                    raise
                latest = str(response.get("historyId", latest))
                for record in response.get("history", []):
                    for msg in record.get("messagesAdded", []):
                        results.append(msg["message"])
                request = self._users().history().list_next(request, response)
            return results, latest

        return await self._run(_fetch)

    async def get_messages_after(self, epoch_seconds: int) -> list[dict]:
        """Inbox message stubs received after a Unix time, oldest first.

        Recovery path for ``HistoryExpiredError``.
        """

        def _fetch() -> list[dict]:
            results: list[dict] = []
            request = self._users().messages().list(
                userId="me", q=f"after:{epoch_seconds}", labelIds=["INBOX"]
            )
            while request is not None:
                response = request.execute()
                results.extend(response.get("messages", []))
                request = self._users().messages().list_next(request, response)
            # messages.list is newest first; process in arrival order so a
            # later status overrides an earlier one.
            results.reverse()
            return results

        return await self._run(_fetch)

    async def get_current_history_id(self) -> str:
        def _fetch() -> str:
            return str(self._users().getProfile(userId="me").execute()["historyId"])

        return await self._run(_fetch)

    async def get_message_content(self, message_id: str) -> tuple[str, str, str]:
        """Return ``(subject, body, sender)`` for a message."""

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

        return await self._run(_fetch)

    # ── Watch ────────────────────────────────────────────────────────

    async def setup_watch(self, topic_name: str) -> dict:
        """Register (or renew) push notifications for the inbox.

        Returns the watch response, containing ``historyId`` and
        ``expiration`` (epoch milliseconds).
        """

        def _watch() -> dict:
            body = {"topicName": topic_name, "labelIds": ["INBOX"]}
            return self._users().watch(userId="me", body=body).execute()

        return await self._run(_watch)

    async def stop_watch(self) -> None:
        await self._run(lambda: self._users().stop(userId="me").execute())

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
                # A nested multipart (typically multipart/alternative inside
                # multipart/mixed) already resolved its own best text. Its
                # mime type is never text/*, so keying on that, as this once
                # did, discarded the body of most real-world email.
                if part.get("parts") and plain is None:
                    plain = GmailService._extract_body(part) or None
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
