"""
Connecting a user's Gmail, and a test hook for the classifier.
"""

from __future__ import annotations

import logging

from asyncpg import Connection
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from src.api.dependencies import CurrentUser, get_current_user, get_db
from src.api.routes.auth import check_oauth_state, finish_redirect, start_oauth
from src.core import google_oauth
from src.email_pipeline.accounts import (
    MailboxInUseError,
    connect_account,
    disconnect_account,
)
from src.email_pipeline.extractor import extract_application_event
from src.email_pipeline.processing import handle_event
from src.email_pipeline.schemas import status_for_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/gmail", tags=["Gmail"])

_SETTINGS_PAGE = "/settings"


@router.get("/connect")
async def connect(user: CurrentUser = Depends(get_current_user)):
    """Send the user to Google to grant read access to their inbox."""
    return start_oauth("gmail", google_oauth.GMAIL_CONNECT_SCOPES, login_hint=user.email)


@router.get("/callback")
async def connect_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    user: CurrentUser = Depends(get_current_user),
    conn: Connection = Depends(get_db),
):
    if error:
        return finish_redirect(_SETTINGS_PAGE, "gmail", gmail="cancelled")
    if not code or not check_oauth_state(request, "gmail", state):
        return finish_redirect(_SETTINGS_PAGE, "gmail", gmail="error")

    try:
        grant = await google_oauth.exchange_code("gmail", code)
    except google_oauth.OAuthError:
        logger.exception("Gmail token exchange failed for user %s", user.id)
        return finish_redirect(_SETTINGS_PAGE, "gmail", gmail="error")

    if google_oauth.GMAIL_SCOPE not in grant.scopes:
        # Google's consent screen lets people untick individual permissions.
        return finish_redirect(_SETTINGS_PAGE, "gmail", gmail="scope_missing")
    if not grant.refresh_token:
        return finish_redirect(_SETTINGS_PAGE, "gmail", gmail="error")

    try:
        watching = await connect_account(
            conn, user.id, grant.identity.email, grant.refresh_token
        )
    except MailboxInUseError:
        return finish_redirect(_SETTINGS_PAGE, "gmail", gmail="in_use")
    except Exception:
        # The grant is stored by now; the scheduler retries the watch.
        logger.exception("Gmail watch registration failed for user %s", user.id)
        return finish_redirect(_SETTINGS_PAGE, "gmail", gmail="watch_failed")

    logger.info("User %s connected Gmail %s", user.id, grant.identity.email)
    return finish_redirect(
        _SETTINGS_PAGE, "gmail", gmail="connected" if watching else "connected_no_push"
    )


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect(
    user: CurrentUser = Depends(get_current_user),
    conn: Connection = Depends(get_db),
):
    """Stop reading this user's mail and revoke the grant at Google."""
    await disconnect_account(conn, user.id)


@router.get("/activity")
async def activity(
    limit: int = 50,
    user: CurrentUser = Depends(get_current_user),
    conn: Connection = Depends(get_db),
):
    """Recent emails the pipeline acted on, newest first.

    Ignored (non-application) mail is excluded; nothing about it is stored
    beyond its id.
    """
    rows = await conn.fetch(
        """
        SELECT p.message_id, p.outcome, p.event_type, p.company, p.subject,
               p.processed_at, p.application_id, a.role, a.status
        FROM processed_emails p
        LEFT JOIN applications a ON a.id = p.application_id
        WHERE p.user_id = $1 AND p.outcome <> 'ignored'
        ORDER BY p.processed_at DESC
        LIMIT $2
        """,
        user.id,
        min(max(limit, 1), 200),
    )
    return [dict(r) for r in rows]


class TestEmailPayload(BaseModel):
    raw_text: str
    subject: str = ""
    sender: str = ""
    thread_id: str | None = None
    dry_run: bool = True


@router.post("/test")
async def classify_test_email(
    payload: TestEmailPayload,
    user: CurrentUser = Depends(get_current_user),
    conn: Connection = Depends(get_db),
):
    """Run pasted email text through the classifier, optionally applying it.

    The only way to exercise extraction and matching without a live inbox.
    Dry run by default.
    """
    event = await extract_application_event(payload.subject, payload.raw_text, payload.sender)
    if event is None:
        return {"matched": False, "detail": "Not classified as an application event."}

    mapped = status_for_event(event.event_type)
    response = {
        "matched": True,
        "dry_run": payload.dry_run,
        "extracted_event": event.model_dump(),
        "mapped_status": mapped.value if mapped else None,
    }
    if payload.dry_run:
        return response

    try:
        outcome, application = await handle_event(
            conn,
            user.id,
            event,
            message_id=f"test:{event.company}:{payload.subject}"[:255],
            thread_id=payload.thread_id,
            subject=payload.subject,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return {**response, "outcome": outcome, "application": application}
