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
from datetime import UTC, datetime
from typing import Any

from asyncpg import Connection
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from src.api.dependencies import get_db, verify_pubsub_token
from src.core.config import get_settings
from src.core.state_machine import (
    ApplicationStatus,
    can_transition,
    find_transition_path,
    transition,
)
from src.email_pipeline.extractor import extract_application_event
from src.email_pipeline.gmail_service import GmailAuthError, get_gmail_service
from src.email_pipeline.schemas import ApplicationEvent, status_for_event

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
    subject: str = ""
    sender: str = ""
    thread_id: str | None = None
    dry_run: bool = False


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _get_sync_cursor(conn: Connection, email_address: str) -> str | None:
    """Return the last processed Gmail history id for *email_address*."""
    row = await conn.fetchrow(
        "SELECT last_history_id FROM gmail_sync_state WHERE email_address = $1",
        email_address,
    )
    return row["last_history_id"] if row else None


async def _save_sync_cursor(
    conn: Connection, email_address: str, history_id: str
) -> None:
    """Persist the history id up to which this mailbox has been processed."""
    await conn.execute(
        """
        INSERT INTO gmail_sync_state (email_address, last_history_id)
        VALUES ($1, $2)
        ON CONFLICT (email_address)
        DO UPDATE SET last_history_id = EXCLUDED.last_history_id
        """,
        email_address,
        history_id,
    )


async def _already_processed(conn: Connection, message_id: str) -> bool:
    """Return True when this Gmail message has already been handled."""
    if not message_id:
        return False
    row = await conn.fetchrow(
        "SELECT 1 FROM processed_emails WHERE message_id = $1", message_id
    )
    return row is not None


async def _mark_processed(
    conn: Connection, message_id: str, thread_id: str | None
) -> None:
    """Record a message as handled so redelivery is a no-op."""
    if not message_id:
        return
    await conn.execute(
        """
        INSERT INTO processed_emails (message_id, thread_id)
        VALUES ($1, $2)
        ON CONFLICT (message_id) DO NOTHING
        """,
        message_id,
        thread_id,
    )


async def _match_or_create_application(
    conn: Connection,
    event: ApplicationEvent,
    thread_id: str | None = None,
    subject: str = "",
) -> dict[str, Any]:
    """
    Resolve the application an email refers to, creating one if necessary.

    Matching is tiered, most specific first:

    1. ``email_thread_id`` — a reply in a known thread is unambiguous.
    2. company + role — distinguishes several open applications at one company.
    3. company alone — last resort, most recently updated wins.

    Tier 3 is what the original implementation did exclusively, which meant a
    rejection from a company you had applied to three times would update
    whichever row happened to be touched last.
    """
    company = event.company
    if not company:
        logger.warning("Extracted event has no company – cannot match: %s", event)
        raise ValueError("Cannot match application without a company name.")

    row = None

    # Tier 1: the thread this email belongs to.
    if thread_id:
        row = await conn.fetchrow(
            """
            SELECT * FROM applications
            WHERE email_thread_id = $1 AND deleted_at IS NULL
            LIMIT 1
            """,
            thread_id,
        )

    # Tier 2: company + role.
    if row is None and event.role:
        row = await conn.fetchrow(
            """
            SELECT * FROM applications
            WHERE LOWER(company) = LOWER($1)
              AND LOWER(role) = LOWER($2)
              AND deleted_at IS NULL
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            company,
            event.role,
        )

    # Tier 3: company only.
    if row is None:
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
        application = dict(row)
        # Bind the thread to this application so later replies hit tier 1.
        if thread_id and not application.get("email_thread_id"):
            updated = await conn.fetchrow(
                """
                UPDATE applications SET email_thread_id = $1
                WHERE id = $2 AND email_thread_id IS NULL
                RETURNING *
                """,
                thread_id,
                application["id"],
            )
            if updated is not None:
                application = dict(updated)
        return application

    # Nothing matched – create a new application from what the email told us.
    initial_status = status_for_event(event.event_type) or ApplicationStatus.APPLIED
    new_row = await conn.fetchrow(
        """
        INSERT INTO applications
            (company, role, source, status, notes, email_thread_id)
        VALUES ($1, $2, 'email', $3::application_status, $4, $5)
        RETURNING *
        """,
        company,
        event.role or "Unknown Role",
        initial_status.value,
        f"Auto-created from email: {subject}",
        thread_id,
    )
    logger.info(
        "Auto-created application for '%s' at '%s'", event.role, company
    )
    return dict(new_row)


async def _apply_status_update(
    conn: Connection,
    application: dict[str, Any],
    new_status: ApplicationStatus | None,
) -> dict[str, Any]:
    """
    Apply a status transition to the application if the new status is valid
    and the transition is allowed by the state machine.

    An email can arrive out of order or describe a step already recorded, so
    an illegal transition is logged and ignored rather than raised.

    Emails also skip states. An offer routinely arrives while the application
    still reads INTERVIEW_SCHEDULED, because no email ever announces that an
    interview happened. Requiring a direct edge would silently discard that
    offer, so a destination reachable by a legal chain is accepted and the
    inferred intermediate steps are logged. Genuinely illegal moves — anything
    out of a terminal state — remain blocked, and the manual PATCH route still
    enforces single-step transitions.

    Returns the (possibly updated) application dict.
    """
    if new_status is None:
        return application

    current_status = ApplicationStatus(application["status"])

    if current_status == new_status:
        return application  # no-op

    if not can_transition(current_status, new_status):
        path = find_transition_path(current_status, new_status)
        if not path:
            logger.info(
                "Skipping unreachable transition %s -> %s for application %s",
                current_status.value,
                new_status.value,
                application["id"],
            )
            return application
        logger.info(
            "Inferring skipped states for application %s: %s",
            application["id"],
            " -> ".join([current_status.value, *(s.value for s in path)]),
        )
    else:
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


@router.post(
    "/gmail",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(verify_pubsub_token)],
)
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
    try:
        # 1. Decode the base64-encoded Pub/Sub message data.
        decoded_bytes = base64.b64decode(payload.message.data)
        notification = json.loads(decoded_bytes)
        logger.info("Received Gmail notification: %s", notification)

        email_address: str = notification.get(
            "emailAddress", get_settings().GMAIL_USER_EMAIL
        )
        notified_history_id: str = str(notification.get("historyId", ""))

        if not notified_history_id:
            logger.warning("Notification missing historyId – ignoring.")
            return {"status": "ignored", "reason": "missing historyId"}

        # 2. Resume from the last id we actually processed, NOT from the id in
        #    the notification. Gmail returns history strictly after the start
        #    id, so replaying from the notification's own id would skip the
        #    very message that triggered it.
        cursor = await _get_sync_cursor(conn, email_address)
        if cursor is None:
            # Nothing stored yet: adopt this id as the baseline and wait for
            # the next notification. Backfilling the whole mailbox here would
            # be slow and would re-classify years of old mail.
            await _save_sync_cursor(conn, email_address, notified_history_id)
            logger.info(
                "No sync cursor for %s — baseline set to %s.",
                email_address,
                notified_history_id,
            )
            return {"status": "ok", "processed": 0, "detail": "baseline recorded"}

        gmail = get_gmail_service()
        message_stubs = await gmail.get_new_messages(cursor)

        if not message_stubs:
            logger.info("No new messages since historyId %s", cursor)
            await _save_sync_cursor(conn, email_address, notified_history_id)
            return {"status": "ok", "processed": 0}

        processed_count = 0
        skipped_count = 0
        errors: list[str] = []

        for stub in message_stubs:
            message_id = stub.get("id", "")
            thread_id = stub.get("threadId")
            try:
                # Pub/Sub delivers at-least-once and a single history entry can
                # appear in overlapping windows, so guard against re-work.
                if await _already_processed(conn, message_id):
                    skipped_count += 1
                    continue

                subject, body, sender = await gmail.get_message_content(message_id)

                # 3. Extract a structured event. This is an async call to the
                #    LLM and takes (subject, body, sender) — not a raw message.
                event = await extract_application_event(subject, body, sender)

                await _mark_processed(conn, message_id, thread_id)

                if event is None:
                    # GENERAL, low confidence, or an extraction error.
                    logger.debug("Email %s is not an application event.", message_id)
                    skipped_count += 1
                    continue

                # 4. Match to an existing application, or create one.
                application = await _match_or_create_application(
                    conn, event, thread_id=thread_id, subject=subject
                )

                # 5. Apply the status implied by the event type.
                await _apply_status_update(
                    conn, application, status_for_event(event.event_type)
                )

                processed_count += 1

            except Exception as email_err:
                error_msg = f"Error processing email {message_id}: {email_err}"
                logger.exception(error_msg)
                errors.append(error_msg)

        # 6. Advance the cursor only after the batch, so a mid-batch crash
        #    replays the remainder rather than losing it.
        await _save_sync_cursor(conn, email_address, notified_history_id)

        logger.info(
            "Webhook complete – processed: %d, skipped: %d, errors: %d",
            processed_count,
            skipped_count,
            len(errors),
        )
        return {
            "status": "ok",
            "processed": processed_count,
            "skipped": skipped_count,
            "errors": len(errors),
        }

    except GmailAuthError as exc:
        # A configuration problem, not a crash. Still 200, because retrying
        # will not fix it and Pub/Sub would redeliver forever.
        logger.error("Gmail credentials unusable — cannot process webhook: %s", exc)
        return {"status": "error", "detail": "gmail credentials not configured"}

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
    extraction pipeline. Useful during development and integration testing,
    and the only path that exercises extraction without a live Gmail webhook.

    Set ``dry_run`` to classify the email without writing to the database.
    """
    event = await extract_application_event(
        payload.subject, payload.raw_text, payload.sender
    )

    if event is None:
        return {
            "matched": False,
            "detail": (
                "Extractor did not detect a job-application event "
                "(classified GENERAL, or confidence below 0.5)."
            ),
        }

    mapped_status = status_for_event(event.event_type)

    if payload.dry_run:
        return {
            "matched": True,
            "dry_run": True,
            "extracted_event": event.model_dump(),
            "mapped_status": mapped_status.value if mapped_status else None,
        }

    # Attempt matching / creation just like the real webhook.
    try:
        application = await _match_or_create_application(
            conn, event, thread_id=payload.thread_id, subject=payload.subject
        )
        updated = await _apply_status_update(conn, application, mapped_status)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    return {
        "matched": True,
        "extracted_event": event.model_dump(),
        "mapped_status": mapped_status.value if mapped_status else None,
        "application": updated,
    }


# ---------------------------------------------------------------------------
# POST /gmail/watch — register or renew the Gmail push subscription
# ---------------------------------------------------------------------------


@router.post("/gmail/watch", status_code=status.HTTP_200_OK)
async def register_gmail_watch(conn: Connection = Depends(get_db)):
    """
    Register (or renew) the Gmail ``users.watch`` push subscription.

    Gmail caps a watch at 7 days and stops delivering notifications the moment
    it lapses, with no error anywhere — the pipeline simply goes quiet. Call
    this on a schedule (daily is ample) to keep it alive. The scraper's
    EventBridge rule in infra/aws/terraform is the natural place to hang it.
    """
    settings = get_settings()

    if not settings.GOOGLE_CLOUD_PROJECT_ID or not settings.GOOGLE_PUBSUB_TOPIC:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "GOOGLE_CLOUD_PROJECT_ID and GOOGLE_PUBSUB_TOPIC must be set "
                "before a Gmail watch can be registered."
            ),
        )

    topic = (
        f"projects/{settings.GOOGLE_CLOUD_PROJECT_ID}"
        f"/topics/{settings.GOOGLE_PUBSUB_TOPIC}"
    )

    try:
        gmail = get_gmail_service()
        result = await gmail.setup_watch(topic)
    except GmailAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    history_id = str(result.get("historyId", ""))
    # Gmail returns expiration as epoch milliseconds.
    expiration_ms = result.get("expiration")
    expires_at = (
        datetime.fromtimestamp(int(expiration_ms) / 1000, tz=UTC)
        if expiration_ms
        else None
    )

    email_address = settings.GMAIL_USER_EMAIL
    if email_address:
        # Seed the cursor on first registration so the next notification has a
        # baseline to resume from, and record when this watch lapses.
        await conn.execute(
            """
            INSERT INTO gmail_sync_state
                (email_address, last_history_id, watch_expires_at)
            VALUES ($1, $2, $3)
            ON CONFLICT (email_address) DO UPDATE
            SET watch_expires_at = EXCLUDED.watch_expires_at,
                last_history_id = COALESCE(
                    gmail_sync_state.last_history_id, EXCLUDED.last_history_id
                )
            """,
            email_address,
            history_id,
            expires_at,
        )

    logger.info(
        "Gmail watch registered on %s — historyId=%s expires=%s",
        topic,
        history_id,
        expires_at,
    )
    return {
        "status": "ok",
        "topic": topic,
        "history_id": history_id,
        "expires_at": expires_at.isoformat() if expires_at else None,
    }
