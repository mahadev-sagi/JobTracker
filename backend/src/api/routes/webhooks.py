"""
Gmail Pub/Sub webhook router.

Receives push notifications from Google Cloud Pub/Sub when new emails arrive
in the user's Gmail inbox, processes them through the extraction pipeline,
and upserts matching job-application records.
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from asyncpg import Connection
from pydantic import BaseModel

from src.core.config import get_settings
from src.core.state_machine import ApplicationStatus, transition, can_transition
from src.api.dependencies import get_db
from src.email_pipeline.extractor import extract_application_event
from src.email_pipeline.gmail_service import GmailService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webhooks", tags=["Webhooks"])

# ---------------------------------------------------------------------------
# Pydantic helpers for incoming Pub/Sub payloads
# ---------------------------------------------------------------------------


class PubSubMessage(BaseModel):
    """Inner message object from a Pub/Sub push payload."""

    data: str  # base64-encoded
    message_id: str | None = None
    publish_time: str | None = None


class PubSubPushPayload(BaseModel):
    """Top-level envelope sent by Google Cloud Pub/Sub."""

    message: PubSubMessage
    subscription: str | None = None


class TestEmailPayload(BaseModel):
    """Body accepted by the test endpoint."""

    raw_text: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _match_or_create_application(
    conn: Connection,
    event: dict[str, Any],
) -> dict[str, Any]:
    """
    Try to find an existing application whose company matches the event.
    If none exists, create a new one.

    Returns the application row as a dict.
    """
    company: str | None = event.get("company")
    if not company:
        logger.warning("Extracted event has no company – skipping match: %s", event)
        raise ValueError("Cannot match application without a company name.")

    # Case-insensitive match on company name.
    row = await conn.fetchrow(
        """
        SELECT * FROM applications
        WHERE LOWER(company) = LOWER($1) AND deleted_at IS NULL
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        company,
    )

    if row is not None:
        return dict(row)

    # No existing application – create one automatically.
    new_row = await conn.fetchrow(
        """
        INSERT INTO applications (company, role, source, status, notes)
        VALUES ($1, $2, 'email', $3, $4)
        RETURNING *
        """,
        company,
        event.get("role", "Unknown Role"),
        event.get("status", ApplicationStatus.APPLIED.value),
        f"Auto-created from email: {event.get('subject', '')}",
    )
    logger.info("Auto-created application for company '%s'", company)
    return dict(new_row)


async def _apply_status_update(
    conn: Connection,
    application: dict[str, Any],
    new_status_str: str | None,
) -> dict[str, Any]:
    """
    Apply a status transition to the application if the new status is valid
    and the transition is allowed by the state machine.

    Returns the (possibly updated) application dict.
    """
    if not new_status_str:
        return application

    try:
        new_status = ApplicationStatus(new_status_str)
    except ValueError:
        logger.warning("Ignoring unknown status '%s' from email extraction.", new_status_str)
        return application

    current_status = ApplicationStatus(application["status"])

    if current_status == new_status:
        return application  # no-op

    if not can_transition(current_status, new_status):
        logger.info(
            "Skipping invalid transition %s -> %s for application %s",
            current_status.value,
            new_status.value,
            application["id"],
        )
        return application

    transition(current_status, new_status)

    row = await conn.fetchrow(
        """
        UPDATE applications
        SET status = $1, updated_at = NOW()
        WHERE id = $2
        RETURNING *
        """,
        new_status.value,
        application["id"],
    )
    logger.info(
        "Transitioned application %s from %s to %s",
        application["id"],
        current_status.value,
        new_status.value,
    )
    return dict(row) if row else application


# ---------------------------------------------------------------------------
# POST /gmail — Pub/Sub push handler
# ---------------------------------------------------------------------------


@router.post("/gmail", status_code=status.HTTP_200_OK)
async def gmail_webhook(
    payload: PubSubPushPayload,
    conn: Connection = Depends(get_db),
):
    """
    Receive a Gmail Pub/Sub push notification.

    Google Cloud Pub/Sub requires that this endpoint always returns 200 OK,
    even if processing fails (to avoid infinite retries). Errors are logged
    but never surfaced as HTTP errors.
    """
    settings = get_settings()

    try:
        # 1. Decode the base64-encoded Pub/Sub message data.
        decoded_bytes = base64.b64decode(payload.message.data)
        notification = json.loads(decoded_bytes)
        logger.info("Received Gmail notification: %s", notification)

        email_address: str = notification.get("emailAddress", "")
        history_id: str = str(notification.get("historyId", ""))

        if not history_id:
            logger.warning("Notification missing historyId – ignoring.")
            return {"status": "ignored", "reason": "missing historyId"}

        # 2. Fetch new emails since the given historyId.
        gmail = GmailService()
        emails = await gmail.get_new_emails(
            email_address=email_address,
            history_id=history_id,
        )

        if not emails:
            logger.info("No new emails found for historyId %s", history_id)
            return {"status": "ok", "processed": 0}

        processed_count = 0
        errors: list[str] = []

        for email in emails:
            try:
                # 3. Extract structured application event from email.
                event = extract_application_event(email)
                if event is None:
                    logger.debug("Email not related to a job application – skipping.")
                    continue

                # 4. Match to existing application or create new.
                application = await _match_or_create_application(conn, event)

                # 5. Apply status transition.
                await _apply_status_update(conn, application, event.get("status"))

                processed_count += 1

            except Exception as email_err:
                error_msg = f"Error processing email: {email_err}"
                logger.exception(error_msg)
                errors.append(error_msg)

        logger.info(
            "Webhook processing complete – processed: %d, errors: %d",
            processed_count,
            len(errors),
        )
        return {
            "status": "ok",
            "processed": processed_count,
            "errors": len(errors),
        }

    except Exception:
        # Catch-all: always return 200 to Pub/Sub so it doesn't redeliver.
        logger.exception("Unexpected error in Gmail webhook handler")
        return {"status": "error", "detail": "internal processing error"}


# ---------------------------------------------------------------------------
# POST /gmail/test — manual testing endpoint
# ---------------------------------------------------------------------------


@router.post("/gmail/test")
async def gmail_webhook_test(
    payload: TestEmailPayload,
    conn: Connection = Depends(get_db),
):
    """
    Test endpoint that accepts raw email text and runs it through the
    extraction pipeline. Useful during development and integration testing.
    """
    event = extract_application_event(payload.raw_text)

    if event is None:
        return {
            "matched": False,
            "detail": "Extractor did not detect a job-application event.",
        }

    # Attempt matching / creation just like the real webhook.
    try:
        application = await _match_or_create_application(conn, event)
        updated = await _apply_status_update(conn, application, event.get("status"))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    return {
        "matched": True,
        "extracted_event": event,
        "application": updated,
    }
