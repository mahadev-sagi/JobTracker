"""Email-to-application processing against a real database.

Gmail and the LLM are faked; matching, transitions, bookkeeping and the sync
cursor run for real.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta

import asyncpg
import httpx
import pytest
from src.core.security import encrypt_secret
from src.email_pipeline import processing
from src.email_pipeline.gmail_service import (
    GmailAuthError,
    GmailService,
    HistoryExpiredError,
)
from src.email_pipeline.processing import (
    MailboxBusyError,
    SyncFailedError,
    apply_status_update,
    handle_event,
    normalize_company,
    resolve_application,
    sync_mailbox,
)
from src.email_pipeline.schemas import ApplicationEvent, EmailEventType

from tests.conftest import TEST_DATABASE_URL, make_user

pytestmark = pytest.mark.asyncio

REJECTION = EmailEventType.REJECTION
OFFER = EmailEventType.OFFER
CONFIRMATION = EmailEventType.APPLICATION_CONFIRMATION


def event(event_type=REJECTION, company="Stripe", role=None):
    return ApplicationEvent(event_type=event_type, company=company, role=role, confidence=0.9)


async def add_app(db, user_id, company="Stripe", role="Backend Engineer", status="APPLIED", thread=None):
    row = await db.fetchrow(
        """
        INSERT INTO applications (user_id, company, role, status, email_thread_id)
        VALUES ($1, $2, $3, $4::application_status, $5) RETURNING *
        """,
        user_id,
        company,
        role,
        status,
        thread,
    )
    return dict(row)


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

async def test_company_names_normalise():
    assert normalize_company("Stripe, Inc.") == normalize_company("stripe")
    assert normalize_company("Acme Corp") == normalize_company("ACME")
    assert normalize_company("Jane Street") != normalize_company("Street")


async def test_thread_wins_over_company(db):
    user = await make_user(db)
    threaded = await add_app(db, user, company="Other", thread="T-1")
    await add_app(db, user, company="Stripe")
    app, how = await resolve_application(db, user, event(), "T-1")
    assert (app["id"], how) == (threaded["id"], "matched")


async def test_company_and_role_match_despite_spelling(db):
    user = await make_user(db)
    await add_app(db, user, company="Stripe, Inc.", role="Data Scientist")
    target = await add_app(db, user, company="Stripe, Inc.", role="Backend Engineer")
    app, how = await resolve_application(db, user, event(role="backend engineer"), None)
    assert (app["id"], how) == (target["id"], "matched")


async def test_company_only_matches_a_single_open_application(db):
    user = await make_user(db)
    await add_app(db, user, role="Old role", status="REJECTED")
    target = await add_app(db, user, role="Backend Engineer")
    app, how = await resolve_application(db, user, event(), None)
    assert (app["id"], how) == (target["id"], "matched")


async def test_company_only_with_several_open_applications_is_ambiguous(db):
    user = await make_user(db)
    a = await add_app(db, user, role="Backend Engineer")
    b = await add_app(db, user, role="Data Scientist")
    outcome, _ = await handle_event(
        db, user, event(), message_id="m1", thread_id=None, subject="Update"
    )
    assert outcome == "ambiguous"
    statuses = await db.fetch(
        "SELECT status FROM applications WHERE id = ANY($1::uuid[])", [a["id"], b["id"]]
    )
    assert {r["status"] for r in statuses} == {"APPLIED"}
    assert await db.fetchval(
        "SELECT outcome FROM processed_emails WHERE message_id = 'm1'"
    ) == "ambiguous"


async def test_confirmation_for_an_unknown_role_creates_a_new_application(db):
    user = await make_user(db)
    await add_app(db, user, role="Backend Engineer")
    _, how = await resolve_application(
        db, user, event(CONFIRMATION, role="Frontend Engineer"), None
    )
    assert how == "create"


async def test_never_matches_another_users_application(db):
    alice = await make_user(db, "alice@example.com")
    bob = await make_user(db, "bob@example.com")
    await add_app(db, alice, thread="T-1")
    _, how = await resolve_application(db, bob, event(), "T-1")
    assert how == "create"


async def test_created_application_belongs_to_the_user_and_binds_thread(db):
    user = await make_user(db)
    outcome, app = await handle_event(
        db, user, event(CONFIRMATION, role="SWE"), message_id="m", thread_id="T", subject="Thanks"
    )
    assert outcome == "created"
    assert (app["user_id"], app["email_thread_id"], app["status"]) == (user, "T", "APPLIED")


# ---------------------------------------------------------------------------
# Transitions
# ---------------------------------------------------------------------------

async def test_offer_while_interview_scheduled_is_applied(db):
    user = await make_user(db)
    app = await add_app(db, user, status="INTERVIEW_SCHEDULED")
    updated, changed = await apply_status_update(db, app, processing.ApplicationStatus.OFFERED)
    assert changed and updated["status"] == "OFFERED"


async def test_terminal_state_is_never_revived(db):
    user = await make_user(db)
    app = await add_app(db, user, status="REJECTED")
    updated, changed = await apply_status_update(db, app, processing.ApplicationStatus.OFFERED)
    assert not changed and updated["status"] == "REJECTED"


# ---------------------------------------------------------------------------
# Mailbox sync
# ---------------------------------------------------------------------------

class FakeGmail:
    def __init__(self, stubs=None, latest="500", expired=False, fail_on=None, revoked=False):
        self.stubs = stubs or []
        self.latest = latest
        self.expired = expired
        self.fail_on = fail_on
        self.revoked = revoked
        self.scanned_after = None

    async def get_new_messages(self, history_id):
        if self.revoked:
            raise GmailAuthError("invalid_grant")
        if self.expired:
            raise HistoryExpiredError(history_id)
        return self.stubs, self.latest

    async def get_messages_after(self, epoch):
        self.scanned_after = epoch
        return self.stubs

    async def get_current_history_id(self):
        return self.latest

    async def get_message_content(self, message_id):
        if message_id == self.fail_on:
            raise RuntimeError("Gmail unavailable")
        return f"subject {message_id}", "body", "jobs@stripe.com"


async def connected_user(db, cursor="100", synced_at=None):
    user = await make_user(db)
    await db.execute(
        """
        INSERT INTO gmail_accounts
            (user_id, email_address, refresh_token_encrypted, last_history_id, last_synced_at)
        VALUES ($1, 'alice@gmail.com', $2, $3, $4)
        """,
        user,
        encrypt_secret("refresh-token"),
        cursor,
        synced_at,
    )
    return user


@pytest.fixture
def fake_gmail(monkeypatch):
    holder = {}

    def install(gmail):
        holder["gmail"] = gmail
        monkeypatch.setattr(processing, "gmail_for_account", lambda account: gmail)
        return gmail

    async def classify(subject, body, sender):
        return event(REJECTION, company="Stripe", role="Backend Engineer")

    monkeypatch.setattr(processing, "extract_application_event", classify)
    return install


async def cursor(db, user):
    return await db.fetchval("SELECT last_history_id FROM gmail_accounts WHERE user_id = $1", user)


async def test_sync_applies_updates_and_advances_cursor(db, fake_gmail):
    user = await connected_user(db)
    app = await add_app(db, user)
    fake_gmail(FakeGmail(stubs=[{"id": "m1", "threadId": "t1"}], latest="500"))

    result = await sync_mailbox(db, user, "450")

    assert (result.status, result.processed) == ("ok", 1)
    assert await cursor(db, user) == "500"
    row = await db.fetchrow("SELECT status, email_thread_id FROM applications WHERE id = $1", app["id"])
    assert tuple(row) == ("REJECTED", "t1")


async def test_redelivery_is_a_no_op(db, fake_gmail):
    user = await connected_user(db)
    await add_app(db, user)
    fake_gmail(FakeGmail(stubs=[{"id": "m1", "threadId": "t1"}]))
    await sync_mailbox(db, user)
    result = await sync_mailbox(db, user)
    assert (result.processed, result.skipped) == (0, 1)


async def test_failed_message_keeps_cursor_and_later_messages_still_processed(db, fake_gmail):
    user = await connected_user(db)
    await add_app(db, user)
    fake_gmail(FakeGmail(stubs=[{"id": "bad"}, {"id": "good"}], latest="500", fail_on="bad"))

    with pytest.raises(SyncFailedError):
        await sync_mailbox(db, user)

    assert await cursor(db, user) == "100"
    done = await db.fetch("SELECT message_id FROM processed_emails")
    assert [r["message_id"] for r in done] == ["good"]
    assert await db.fetchval("SELECT last_error FROM gmail_accounts") is not None


async def test_cursor_never_moves_backwards(db, fake_gmail):
    user = await connected_user(db, cursor="900")
    fake_gmail(FakeGmail(latest="500"))
    await sync_mailbox(db, user)
    assert await cursor(db, user) == "900"


async def test_first_notification_sets_a_baseline_without_backfilling(db, fake_gmail):
    user = await connected_user(db, cursor=None)
    gmail = fake_gmail(FakeGmail(stubs=[{"id": "old"}]))
    result = await sync_mailbox(db, user, "777")
    assert result.status == "baseline"
    assert await cursor(db, user) == "777"
    assert gmail.scanned_after is None
    assert await db.fetchval("SELECT COUNT(*) FROM processed_emails") == 0


async def test_expired_history_recovers_by_date(db, fake_gmail):
    synced = datetime.now(UTC) - timedelta(days=10)
    user = await connected_user(db, cursor="100", synced_at=synced)
    await add_app(db, user)
    gmail = fake_gmail(FakeGmail(stubs=[{"id": "m1"}], latest="9000", expired=True))

    result = await sync_mailbox(db, user)

    assert result.recovered and result.processed == 1
    assert await cursor(db, user) == "9000"
    # Scans from before the last sync, with a margin.
    assert gmail.scanned_after < synced.timestamp()


async def test_revoked_access_marks_account_and_acknowledges(db, fake_gmail):
    user = await connected_user(db)
    fake_gmail(FakeGmail(revoked=True))
    result = await sync_mailbox(db, user)
    assert result.status == "revoked"
    assert await db.fetchval("SELECT status FROM gmail_accounts") == "revoked"
    assert (await sync_mailbox(db, user)).status == "inactive"


async def test_concurrent_delivery_for_same_mailbox_is_refused(db, fake_gmail):
    user = await connected_user(db)
    fake_gmail(FakeGmail())
    other = await asyncpg.connect(TEST_DATABASE_URL)
    try:
        await other.execute(
            "SELECT pg_advisory_lock(hashtextextended($1, 0))", f"gmail:{user}"
        )
        with pytest.raises(MailboxBusyError):
            await sync_mailbox(db, user)
    finally:
        await other.close()
    assert (await sync_mailbox(db, user)).status == "ok"


# ---------------------------------------------------------------------------
# Webhook
# ---------------------------------------------------------------------------

def push(email="alice@gmail.com", history_id="600"):
    import json

    data = base64.b64encode(
        json.dumps({"emailAddress": email, "historyId": history_id}).encode()
    ).decode()
    return {"message": {"data": data}}


@pytest.fixture
def webhook_client(api):
    async def make():
        from src.main import app

        await api("setup@example.com")  # installs the database override
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": "Bearer test-secret"},
        )

    return make


async def test_webhook_rejects_bad_token(webhook_client):
    async with await webhook_client() as client:
        response = await client.post(
            "/api/webhooks/gmail", json=push(), headers={"Authorization": "Bearer wrong"}
        )
    assert response.status_code == 401


async def test_webhook_acknowledges_unknown_mailbox_and_garbage(webhook_client):
    async with await webhook_client() as client:
        unknown = await client.post("/api/webhooks/gmail", json=push("nobody@gmail.com"))
        garbage = await client.post("/api/webhooks/gmail", json={"message": {"data": "!!"}})
    assert (unknown.status_code, unknown.json()["status"]) == (200, "ignored")
    assert (garbage.status_code, garbage.json()["status"]) == (200, "ignored")


async def test_webhook_retries_failed_sync(db, webhook_client, fake_gmail):
    await connected_user(db)
    fake_gmail(FakeGmail(stubs=[{"id": "bad"}], fail_on="bad"))
    async with await webhook_client() as client:
        response = await client.post("/api/webhooks/gmail", json=push())
    assert response.status_code == 503


async def test_webhook_processes_mail(db, webhook_client, fake_gmail):
    user = await connected_user(db)
    await add_app(db, user)
    fake_gmail(FakeGmail(stubs=[{"id": "m1"}], latest="600"))
    async with await webhook_client() as client:
        response = await client.post("/api/webhooks/gmail", json=push("ALICE@gmail.com"))
    assert response.status_code == 200
    assert response.json()["processed"] == 1


# ---------------------------------------------------------------------------
# MIME parsing
# ---------------------------------------------------------------------------

def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode()


async def test_body_is_found_inside_nested_multipart():
    """multipart/mixed > multipart/alternative > text/plain is how most real
    mail is shaped; the body used to come back empty."""
    payload = {
        "mimeType": "multipart/mixed",
        "parts": [
            {
                "mimeType": "multipart/alternative",
                "body": {},
                "parts": [
                    {"mimeType": "text/plain", "body": {"data": _b64("We regret to inform")}},
                    {"mimeType": "text/html", "body": {"data": _b64("<p>We regret</p>")}},
                ],
            },
            {"mimeType": "application/pdf", "body": {"attachmentId": "x"}},
        ],
    }
    assert GmailService._extract_body(payload) == "We regret to inform"
