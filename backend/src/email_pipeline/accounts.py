"""
Connecting, renewing and disconnecting a user's Gmail.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from asyncpg import Connection

from src.core import google_oauth
from src.core.config import get_settings
from src.core.security import decrypt_secret, encrypt_secret
from src.email_pipeline.gmail_service import GmailAuthError, GmailService
from src.email_pipeline.processing import gmail_for_account, mark_revoked

logger = logging.getLogger(__name__)


class MailboxInUseError(RuntimeError):
    """The mailbox is already connected to a different user."""


async def register_watch(conn: Connection, user_id: UUID, gmail: GmailService) -> bool:
    """Start or renew push notifications. Returns False if Pub/Sub is unset."""
    topic = get_settings().pubsub_topic
    if topic is None:
        logger.warning("GOOGLE_CLOUD_PROJECT_ID is unset; Gmail push is disabled.")
        return False
    result = await gmail.setup_watch(topic)
    expires_at = datetime.fromtimestamp(int(result["expiration"]) / 1000, tz=UTC)
    # Seed the cursor on first registration only. Overwriting an existing one
    # would skip whatever arrived since it was last processed.
    await conn.execute(
        """
        UPDATE gmail_accounts
        SET watch_expires_at = $2,
            last_history_id = COALESCE(last_history_id, $3)
        WHERE user_id = $1
        """,
        user_id,
        expires_at,
        str(result["historyId"]),
    )
    return True


async def connect_account(
    conn: Connection, user_id: UUID, email_address: str, refresh_token: str
) -> bool:
    """Store a fresh grant and start notifications. Returns the watch state."""
    owner = await conn.fetchval(
        "SELECT user_id FROM gmail_accounts WHERE email_address = $1", email_address
    )
    if owner is not None and owner != user_id:
        raise MailboxInUseError(email_address)

    # Reconnecting a different mailbox, or the same one after a revocation,
    # resets the cursor: history ids are per mailbox, and an old one would
    # force an expensive recovery scan.
    await conn.execute(
        """
        INSERT INTO gmail_accounts (user_id, email_address, refresh_token_encrypted)
        VALUES ($1, $2, $3)
        ON CONFLICT (user_id) DO UPDATE
        SET email_address = EXCLUDED.email_address,
            refresh_token_encrypted = EXCLUDED.refresh_token_encrypted,
            status = 'active',
            last_error = NULL,
            last_history_id = CASE
                WHEN gmail_accounts.email_address = EXCLUDED.email_address
                 AND gmail_accounts.status = 'active'
                THEN gmail_accounts.last_history_id
            END,
            last_synced_at = CASE
                WHEN gmail_accounts.email_address = EXCLUDED.email_address
                 AND gmail_accounts.status = 'active'
                THEN gmail_accounts.last_synced_at
                ELSE NOW()
            END
        """,
        user_id,
        email_address,
        encrypt_secret(refresh_token),
    )
    return await register_watch(conn, user_id, GmailService(refresh_token))


async def disconnect_account(conn: Connection, user_id: UUID) -> None:
    account = await conn.fetchrow(
        "SELECT * FROM gmail_accounts WHERE user_id = $1", user_id
    )
    if account is None:
        return
    # Best effort on Google's side; the local row goes regardless, so a
    # failure here can never leave someone unable to disconnect.
    try:
        token = decrypt_secret(account["refresh_token_encrypted"])
        if account["status"] == "active":
            await GmailService(token).stop_watch()
        await google_oauth.revoke_token(token)
    except Exception:
        logger.warning("Could not revoke Gmail access for user %s", user_id, exc_info=True)
    await conn.execute("DELETE FROM gmail_accounts WHERE user_id = $1", user_id)


async def renew_expiring_watches(conn: Connection) -> int:
    """Renew every watch expiring within two days. Returns how many renewed.

    Gmail stops a watch after seven days without any error anywhere — the
    pipeline simply goes quiet — so this runs from the scheduler.
    """
    if get_settings().pubsub_topic is None:
        return 0
    rows = await conn.fetch(
        """
        SELECT * FROM gmail_accounts
        WHERE status = 'active'
          AND (watch_expires_at IS NULL OR watch_expires_at < NOW() + INTERVAL '2 days')
        """
    )
    renewed = 0
    for row in rows:
        try:
            await register_watch(conn, row["user_id"], gmail_for_account(dict(row)))
            renewed += 1
        except GmailAuthError:
            await mark_revoked(conn, row["user_id"], "Google access was revoked or expired.")
        except Exception:
            logger.exception("Failed to renew Gmail watch for user %s", row["user_id"])
    return renewed
