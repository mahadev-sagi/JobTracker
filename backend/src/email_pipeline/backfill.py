"""Manual date-based scans, using the same mailbox lock and deduplication as push."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, time
from uuid import UUID

from src.db.database import get_connection
from src.email_pipeline.gmail_service import GmailAuthError
from src.email_pipeline.processing import _process_message, gmail_for_account, mark_revoked

logger = logging.getLogger(__name__)


async def run_scan(scan_id: UUID, user_id: UUID) -> None:
    async with get_connection() as conn:
        lock_key = f"gmail:{user_id}"
        locked = await conn.fetchval(
            "SELECT pg_try_advisory_lock(hashtextextended($1, 0))", lock_key
        )
        try:
            if not locked:
                raise RuntimeError("Gmail is already being checked. Try again shortly.")
            scan = await conn.fetchrow("SELECT * FROM gmail_scans WHERE id = $1", scan_id)
            account = await conn.fetchrow(
                "SELECT * FROM gmail_accounts WHERE user_id = $1", user_id
            )
            if account is None or account["status"] != "active":
                raise RuntimeError("Connect or reconnect Gmail before scanning.")
            await conn.execute(
                "UPDATE gmail_scans SET status = 'running', updated_at = NOW() WHERE id = $1",
                scan_id,
            )
            gmail = gmail_for_account(dict(account))
            since = int(datetime.combine(scan["start_date"], time.min, tzinfo=UTC).timestamp())
            stubs = await gmail.get_messages_after(since - 1, inbox_only=scan["inbox_only"])
            await conn.execute(
                "UPDATE gmail_scans SET total = $2, updated_at = NOW() WHERE id = $1",
                scan_id, len(stubs),
            )
            for stub in stubs:
                try:
                    outcome = await _process_message(conn, user_id, gmail, stub)
                except GmailAuthError:
                    raise
                except Exception:
                    logger.exception("Email scan message failed for user %s", user_id)
                    await conn.execute(
                        "UPDATE gmail_scans SET errors = errors + 1, updated_at = NOW() WHERE id = $1",
                        scan_id,
                    )
                    continue
                await conn.execute(
                    """UPDATE gmail_scans SET processed = processed + $2,
                       skipped = skipped + $3, updated_at = NOW() WHERE id = $1""",
                    scan_id, int(outcome != "duplicate"), int(outcome == "duplicate"),
                )
            # Historical scans must not advance the incremental inbox cursor.
            await conn.execute(
                """UPDATE gmail_scans SET status = CASE WHEN errors > 0 THEN 'partial'
                   ELSE 'completed' END, updated_at = NOW() WHERE id = $1""", scan_id,
            )
        except Exception as exc:
            logger.exception("Gmail scan failed for user %s", user_id)
            detail = "Scan failed. Try again; already processed emails will be skipped."
            if isinstance(exc, GmailAuthError):
                detail = "Gmail access expired. Reconnect Gmail and try again."
                await mark_revoked(conn, user_id, detail)
            elif isinstance(exc, RuntimeError):
                detail = str(exc)
            await conn.execute(
                """UPDATE gmail_scans SET status = 'failed', detail = $2,
                   updated_at = NOW() WHERE id = $1""", scan_id, detail,
            )
        finally:
            if locked:
                await conn.execute(
                    "SELECT pg_advisory_unlock(hashtextextended($1, 0))", lock_key
                )
