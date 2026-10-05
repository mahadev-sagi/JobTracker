"""
Turning a user's new Gmail messages into application updates.

``sync_mailbox`` is the single entry point, called by the Pub/Sub webhook. It
serialises work per mailbox, resumes from the stored history cursor, falls
back to a date-based scan when Gmail has expired that history, and advances
the cursor only once every message in the batch has been handled.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any
from uuid import UUID

from asyncpg import Connection

from src.core.security import TokenEncryptionError, decrypt_secret
from src.core.state_machine import (
    VALID_TRANSITIONS,
    ApplicationStatus,
    can_transition,
    find_transition_path,
)
from src.email_pipeline.extractor import extract_application_event
from src.email_pipeline.gmail_service import (
    GmailAuthError,
    GmailService,
    HistoryExpiredError,
)
from src.email_pipeline.schemas import (
    ApplicationEvent,
    EmailEventType,
    status_for_event,
)

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = frozenset(s for s, nxt in VALID_TRANSITIONS.items() if not nxt)

# Overlap when recovering by date. Re-reading a few messages is harmless
# because processed_emails dedupes them; missing one is not.
_RECOVERY_MARGIN = timedelta(hours=1)


class MailboxBusyError(RuntimeError):
    """Another delivery is already syncing this mailbox; retry later."""


class SyncFailedError(RuntimeError):
    """At least one message failed; the cursor was not advanced."""


@dataclass
class SyncResult:
    status: str  # ok | baseline | revoked | inactive
    processed: int = 0
    skipped: int = 0
    recovered: bool = False
    outcomes: dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

_COMPANY_SUFFIXES = re.compile(
    r"\b(inc|incorporated|llc|ltd|limited|corp|corporation|co|company|plc|gmbh)\b\.?"
)
_NON_WORD = re.compile(r"[^a-z0-9]+")


def normalize_company(name: str) -> str:
    """'Stripe, Inc.' and 'stripe' must compare equal; the LLM and the job
    board rarely spell a company identically."""
    text = _COMPANY_SUFFIXES.sub(" ", name.lower())
    return _NON_WORD.sub(" ", text).strip()


def normalize_role(role: str) -> str:
    return _NON_WORD.sub(" ", role.lower()).strip()


def _is_open(app: dict[str, Any]) -> bool:
    return ApplicationStatus(app["status"]) not in TERMINAL_STATUSES


def _most_relevant(apps: list[dict[str, Any]]) -> dict[str, Any]:
    """Prefer open applications, then the most recently touched."""
    return max(apps, key=lambda a: (_is_open(a), a["updated_at"]))


async def resolve_application(
    conn: Connection,
    user_id: UUID,
    event: ApplicationEvent,
    thread_id: str | None,
) -> tuple[dict[str, Any] | None, str]:
    """
    Find the user's application this email is about.

    Returns ``(application, "matched")``, ``(None, "create")`` when a new
    application should be recorded, or ``(None, "ambiguous")`` when the email
    could refer to several and guessing would corrupt one of them.

    Tiers, most specific first:

    1. Email thread already bound to an application.
    2. Same company and role.
    3. Company alone — only if exactly one *open* application exists there.
       Picking "the most recently updated" instead, as this once did, moved
       the wrong application whenever someone had applied to several roles
       at one company.
    """
    if thread_id:
        row = await conn.fetchrow(
            """
            SELECT * FROM applications
            WHERE user_id = $1 AND email_thread_id = $2 AND deleted_at IS NULL
            LIMIT 1
            """,
            user_id,
            thread_id,
        )
        if row is not None:
            return dict(row), "matched"

    company = normalize_company(event.company)
    rows = await conn.fetch(
        "SELECT * FROM applications WHERE user_id = $1 AND deleted_at IS NULL",
        user_id,
    )
    at_company = [dict(r) for r in rows if normalize_company(r["company"]) == company]
    if not at_company:
        return None, "create"

    if event.role:
        role = normalize_role(event.role)
        same_role = [a for a in at_company if normalize_role(a["role"]) == role]
        if same_role:
            return _most_relevant(same_role), "matched"
        # A confirmation naming a role we have no record of is a new
        # application, not news about an existing one.
        if event.event_type == EmailEventType.APPLICATION_CONFIRMATION:
            return None, "create"

    open_apps = [a for a in at_company if _is_open(a)]
    if len(open_apps) == 1:
        return open_apps[0], "matched"
    if not open_apps and event.event_type == EmailEventType.APPLICATION_CONFIRMATION:
        return None, "create"
    return None, "ambiguous"


async def bind_thread(
    conn: Connection, application: dict[str, Any], thread_id: str | None
) -> dict[str, Any]:
    """Remember the thread so later replies resolve at tier 1."""
    if not thread_id or application.get("email_thread_id"):
        return application
    row = await conn.fetchrow(
        """
        UPDATE applications SET email_thread_id = $1
        WHERE id = $2 AND email_thread_id IS NULL
        RETURNING *
        """,
        thread_id,
        application["id"],
    )
    return dict(row) if row else application


async def create_application(
    conn: Connection,
    user_id: UUID,
    event: ApplicationEvent,
    thread_id: str | None,
    subject: str,
) -> dict[str, Any]:
    initial = status_for_event(event.event_type) or ApplicationStatus.APPLIED
    row = await conn.fetchrow(
        """
        INSERT INTO applications
            (user_id, company, role, source, status, notes, email_thread_id)
        VALUES ($1, $2, $3, 'email', $4::application_status, $5, $6)
        RETURNING *
        """,
        user_id,
        event.company,
        event.role or "Unknown Role",
        initial.value,
        f"Auto-created from email: {subject}",
        thread_id,
    )
    return dict(row)


async def apply_status_update(
    conn: Connection,
    application: dict[str, Any],
    new_status: ApplicationStatus | None,
) -> tuple[dict[str, Any], bool]:
    """
    Move the application to ``new_status`` if the state machine permits it.

    Returns ``(application, changed)``.

    An email can arrive out of order or restate a step already recorded, so
    an illegal transition is logged and ignored rather than raised.

    Emails also skip states. An offer routinely arrives while the application
    still reads INTERVIEW_SCHEDULED, because no email ever announces that an
    interview happened. Requiring a direct edge would silently discard that
    offer, so a destination reachable by a legal chain is accepted. Anything
    out of a terminal state remains blocked, and the manual PATCH route still
    enforces single-step transitions.
    """
    if new_status is None:
        return application, False
    current = ApplicationStatus(application["status"])
    if current == new_status:
        return application, False
    if not can_transition(current, new_status):
        path = find_transition_path(current, new_status)
        if not path:
            logger.info(
                "Skipping unreachable transition %s -> %s for application %s",
                current.value,
                new_status.value,
                application["id"],
            )
            return application, False
        logger.info(
            "Inferring skipped states for application %s: %s",
            application["id"],
            " -> ".join([current.value, *(s.value for s in path)]),
        )
    row = await conn.fetchrow(
        "UPDATE applications SET status = $1 WHERE id = $2 RETURNING *",
        new_status.value,
        application["id"],
    )
    return (dict(row), True) if row else (application, False)


# ---------------------------------------------------------------------------
# Per-message handling
# ---------------------------------------------------------------------------

async def already_processed(conn: Connection, user_id: UUID, message_id: str) -> bool:
    return bool(
        await conn.fetchval(
            "SELECT 1 FROM processed_emails WHERE user_id = $1 AND message_id = $2",
            user_id,
            message_id,
        )
    )


async def record_processed(
    conn: Connection,
    user_id: UUID,
    message_id: str,
    thread_id: str | None,
    outcome: str,
    *,
    application_id: UUID | None = None,
    event: ApplicationEvent | None = None,
    subject: str | None = None,
) -> None:
    await conn.execute(
        """
        INSERT INTO processed_emails
            (user_id, message_id, thread_id, outcome, application_id,
             event_type, company, subject)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        ON CONFLICT (user_id, message_id) DO NOTHING
        """,
        user_id,
        message_id,
        thread_id,
        outcome,
        application_id,
        event.event_type.value if event else None,
        event.company if event else None,
        subject,
    )


async def handle_event(
    conn: Connection,
    user_id: UUID,
    event: ApplicationEvent,
    *,
    message_id: str,
    thread_id: str | None,
    subject: str,
) -> tuple[str, dict[str, Any] | None]:
    """Apply one classified email atomically. Returns ``(outcome, application)``."""
    async with conn.transaction():
        application, resolution = await resolve_application(
            conn, user_id, event, thread_id
        )
        if resolution == "create":
            application = await create_application(
                conn, user_id, event, thread_id, subject
            )
            outcome = "created"
        elif resolution == "ambiguous":
            logger.info(
                "Email %s about %s matches several applications; left unchanged.",
                message_id,
                event.company,
            )
            outcome = "ambiguous"
        else:
            application = await bind_thread(conn, application, thread_id)
            application, changed = await apply_status_update(
                conn, application, status_for_event(event.event_type)
            )
            outcome = "updated" if changed else "unchanged"
        await record_processed(
            conn,
            user_id,
            message_id,
            thread_id,
            outcome,
            application_id=application["id"] if application else None,
            event=event,
            subject=subject,
        )
    return outcome, application


async def _process_message(
    conn: Connection, user_id: UUID, gmail: GmailService, stub: dict
) -> str:
    message_id = stub["id"]
    thread_id = stub.get("threadId")
    # Pub/Sub delivers at least once, and recovery scans overlap on purpose.
    if await already_processed(conn, user_id, message_id):
        return "duplicate"

    subject, body, sender = await gmail.get_message_content(message_id)
    event = await extract_application_event(subject, body, sender)
    if event is None:
        # Not about an application. Recorded so it is never re-classified,
        # but without the subject: there is no reason to keep it.
        await record_processed(conn, user_id, message_id, thread_id, "ignored")
        return "ignored"

    outcome, _ = await handle_event(
        conn,
        user_id,
        event,
        message_id=message_id,
        thread_id=thread_id,
        subject=subject,
    )
    return outcome


# ---------------------------------------------------------------------------
# Mailbox sync
# ---------------------------------------------------------------------------

def gmail_for_account(account: dict[str, Any]) -> GmailService:
    return GmailService(decrypt_secret(account["refresh_token_encrypted"]))


async def save_cursor(conn: Connection, user_id: UUID, history_id: str) -> None:
    """Record progress, never moving the cursor backwards.

    Deliveries are serialised by the advisory lock, but a delayed notification
    carrying an older id must still not rewind it; that would replay history
    already handled, or with an expired id, force a needless recovery.
    """
    await conn.execute(
        """
        UPDATE gmail_accounts
        SET last_history_id = CASE
                WHEN last_history_id IS NULL
                  OR last_history_id::numeric < $2::text::numeric THEN $2::text
                ELSE last_history_id
            END,
            last_synced_at = NOW(),
            last_error = NULL
        WHERE user_id = $1
        """,
        user_id,
        history_id,
    )


async def mark_revoked(conn: Connection, user_id: UUID, reason: str) -> None:
    await conn.execute(
        """
        UPDATE gmail_accounts
        SET status = 'revoked', last_error = $2, watch_expires_at = NULL
        WHERE user_id = $1
        """,
        user_id,
        reason[:500],
    )


async def sync_mailbox(
    conn: Connection, user_id: UUID, notified_history_id: str | None = None
) -> SyncResult:
    """Process everything new in one user's inbox.

    Raises ``MailboxBusyError`` if another delivery holds the mailbox and
    ``SyncFailedError`` if any message failed; both mean "retry later" and
    leave the cursor where it was.
    """
    lock_key = f"gmail:{user_id}"
    if not await conn.fetchval(
        "SELECT pg_try_advisory_lock(hashtextextended($1, 0))", lock_key
    ):
        raise MailboxBusyError(lock_key)
    try:
        return await _sync_locked(conn, user_id, notified_history_id)
    finally:
        await conn.execute(
            "SELECT pg_advisory_unlock(hashtextextended($1, 0))", lock_key
        )


async def _sync_locked(
    conn: Connection, user_id: UUID, notified_history_id: str | None
) -> SyncResult:
    # Read inside the lock: the previous holder may just have moved the cursor.
    account = await conn.fetchrow(
        "SELECT * FROM gmail_accounts WHERE user_id = $1", user_id
    )
    if account is None or account["status"] != "active":
        return SyncResult(status="inactive")
    account = dict(account)

    try:
        gmail = gmail_for_account(account)
        cursor = account["last_history_id"]
        if cursor is None:
            # No baseline yet. Start from now rather than backfilling the
            # whole mailbox, which would re-classify years of old mail.
            baseline = notified_history_id or await gmail.get_current_history_id()
            await save_cursor(conn, user_id, baseline)
            return SyncResult(status="baseline")

        recovered = False
        try:
            stubs, latest = await gmail.get_new_messages(cursor)
        except HistoryExpiredError:
            since = account["last_synced_at"] or account["created_at"]
            logger.warning(
                "History for user %s expired at %s; rescanning inbox since %s.",
                user_id,
                cursor,
                since,
            )
            # Take the new cursor before listing so anything arriving during
            # the scan is after it, and is picked up next time.
            latest = await gmail.get_current_history_id()
            stubs = await gmail.get_messages_after(
                int((since - _RECOVERY_MARGIN).timestamp())
            )
            recovered = True
    except (GmailAuthError, TokenEncryptionError) as exc:
        logger.warning("Gmail access for user %s is no longer valid: %s", user_id, exc)
        await mark_revoked(conn, user_id, "Google access was revoked or expired.")
        return SyncResult(status="revoked")

    result = SyncResult(status="ok", recovered=recovered)
    errors = 0
    for stub in stubs:
        try:
            outcome = await _process_message(conn, user_id, gmail, stub)
        except GmailAuthError:
            await mark_revoked(conn, user_id, "Google access was revoked or expired.")
            return SyncResult(status="revoked")
        except Exception:
            logger.exception("Failed to process message %s for user %s", stub.get("id"), user_id)
            errors += 1
            continue
        result.outcomes[outcome] = result.outcomes.get(outcome, 0) + 1
        if outcome in ("ignored", "duplicate"):
            result.skipped += 1
        else:
            result.processed += 1

    if errors:
        await conn.execute(
            "UPDATE gmail_accounts SET last_error = $2 WHERE user_id = $1",
            user_id,
            f"{errors} email(s) could not be processed; retrying.",
        )
        raise SyncFailedError(f"{errors} message(s) failed for user {user_id}")

    await save_cursor(conn, user_id, latest)
    return result
