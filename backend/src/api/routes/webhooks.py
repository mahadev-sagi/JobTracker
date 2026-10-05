"""
Gmail Pub/Sub webhook.

Gmail publishes a notification to Pub/Sub whenever a watched inbox changes;
Pub/Sub pushes it here. The notification names the mailbox and its current
history id, nothing more — the messages themselves are fetched by
``sync_mailbox``.

Response codes drive Pub/Sub's redelivery: 2xx acknowledges, anything else is
retried with backoff. Only a fully processed batch is acknowledged.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging

from asyncpg import Connection
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from src.api.dependencies import get_db, verify_pubsub_token
from src.email_pipeline.processing import (
    MailboxBusyError,
    SyncFailedError,
    sync_mailbox,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webhooks", tags=["Webhooks"])


class PubSubMessage(BaseModel):
    """Inner message object from a Pub/Sub push payload."""

    data: str  # base64-encoded
    message_id: str | None = None
    publish_time: str | None = None


class PubSubPushPayload(BaseModel):
    """Top-level envelope sent by Google Cloud Pub/Sub."""

    message: PubSubMessage
    subscription: str | None = None


@router.post(
    "/gmail",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(verify_pubsub_token)],
)
async def gmail_webhook(payload: PubSubPushPayload, conn: Connection = Depends(get_db)):
    try:
        notification = json.loads(base64.b64decode(payload.message.data))
        email_address = str(notification["emailAddress"]).lower()
        history_id = str(notification["historyId"])
    except (binascii.Error, ValueError, KeyError, TypeError):
        # Retrying a malformed message will never succeed; acknowledge it.
        logger.warning("Ignoring malformed Gmail notification")
        return {"status": "ignored", "reason": "malformed"}

    user_id = await conn.fetchval(
        "SELECT user_id FROM gmail_accounts WHERE email_address = $1", email_address
    )
    if user_id is None:
        # Disconnected since the watch was registered. Acknowledge so Pub/Sub
        # stops redelivering; the watch lapses on its own within a week.
        return {"status": "ignored", "reason": "unknown mailbox"}

    try:
        result = await sync_mailbox(conn, user_id, history_id)
    except MailboxBusyError as exc:
        # The delivery in progress may already have listed history before this
        # notification's message arrived, so this one must not be dropped.
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Mailbox busy; retry.") from exc
    except SyncFailedError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Email processing failed; retry delivery."
        ) from exc
    except Exception as exc:
        logger.exception("Unexpected error syncing mailbox for user %s", user_id)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Email processing failed; retry delivery."
        ) from exc

    logger.info(
        "Synced mailbox for user %s: %s processed=%d skipped=%d%s",
        user_id,
        result.status,
        result.processed,
        result.skipped,
        " (recovered)" if result.recovered else "",
    )
    return {
        "status": result.status,
        "processed": result.processed,
        "skipped": result.skipped,
    }
