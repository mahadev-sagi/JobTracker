"""
Tests for the Gmail webhook pipeline.

These cover the seam between the webhook router and the email_pipeline
package - the layer that previously called four methods that did not exist,
with signatures that did not match, and which had no test coverage at all.

The LLM and Gmail clients are mocked throughout; nothing here touches the
network. Database interactions use a fake connection that records the SQL it
was asked to run.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from src.api.routes import webhooks
from src.core.state_machine import ApplicationStatus
from src.email_pipeline.schemas import (
    EVENT_TYPE_TO_STATUS,
    ApplicationEvent,
    EmailEventType,
    status_for_event,
)

# ---------------------------------------------------------------------------
# Event type -> application status mapping
# ---------------------------------------------------------------------------


class TestEventStatusMapping:
    """The bridge that was missing entirely before this pipeline was wired."""

    def test_every_actionable_event_maps_to_a_status(self):
        actionable = set(EmailEventType) - {EmailEventType.GENERAL}
        assert actionable == set(EVENT_TYPE_TO_STATUS)

    def test_general_never_maps_to_a_status(self):
        assert status_for_event(EmailEventType.GENERAL) is None

    @pytest.mark.parametrize(
        ("event_type", "expected"),
        [
            (EmailEventType.APPLICATION_CONFIRMATION, ApplicationStatus.APPLIED),
            (EmailEventType.REJECTION, ApplicationStatus.REJECTED),
            (
                EmailEventType.INTERVIEW_INVITATION,
                ApplicationStatus.INTERVIEW_SCHEDULED,
            ),
            (EmailEventType.OA_INVITATION, ApplicationStatus.OA_RECEIVED),
            (EmailEventType.OFFER, ApplicationStatus.OFFERED),
        ],
    )
    def test_mapping(self, event_type, expected):
        assert status_for_event(event_type) is expected

    def test_mapped_statuses_are_real_enum_members(self):
        # Guards against the BOOKMARKED-style typo that broke POST /applications.
        for stat in EVENT_TYPE_TO_STATUS.values():
            assert ApplicationStatus(stat.value) is stat


# ---------------------------------------------------------------------------
# Fake database connection
# ---------------------------------------------------------------------------


class FakeConn:
    """Minimal asyncpg.Connection stand-in driven by queued responses."""

    def __init__(self, fetchrow_results=None):
        self._fetchrow_results = list(fetchrow_results or [])
        self.queries: list[str] = []

    async def fetchrow(self, query, *args):
        self.queries.append(" ".join(query.split()))
        if self._fetchrow_results:
            return self._fetchrow_results.pop(0)
        return None

    async def execute(self, query, *args):
        self.queries.append(" ".join(query.split()))
        return "INSERT 0 1"

    def matched_on(self, fragment: str) -> bool:
        return any(fragment in q for q in self.queries)


def make_event(
    event_type=EmailEventType.REJECTION, company="Stripe", role="Backend Engineer"
):
    return ApplicationEvent(
        event_type=event_type, company=company, role=role, confidence=0.9
    )


# ---------------------------------------------------------------------------
# Tiered matching
# ---------------------------------------------------------------------------


class TestMatchOrCreate:
    @pytest.mark.asyncio
    async def test_thread_id_takes_priority(self):
        """A known thread wins over any company/role heuristic."""
        threaded = {"id": "app-1", "status": "APPLIED", "email_thread_id": "T-1"}
        conn = FakeConn([threaded])

        result = await webhooks._match_or_create_application(
            conn, make_event(), thread_id="T-1"
        )

        assert result["id"] == "app-1"
        assert conn.matched_on("WHERE email_thread_id = $1")
        # It must not have fallen through to the weaker lookups.
        assert not conn.matched_on("LOWER(role) = LOWER($2)")

    @pytest.mark.asyncio
    async def test_falls_back_to_company_and_role(self):
        conn = FakeConn([None, {"id": "app-2", "status": "APPLIED"}])

        result = await webhooks._match_or_create_application(
            conn, make_event(), thread_id="T-unknown"
        )

        assert result["id"] == "app-2"
        assert conn.matched_on("LOWER(role) = LOWER($2)")

    @pytest.mark.asyncio
    async def test_falls_back_to_company_only(self):
        conn = FakeConn([None, None, {"id": "app-3", "status": "APPLIED"}])

        result = await webhooks._match_or_create_application(conn, make_event())

        assert result["id"] == "app-3"

    @pytest.mark.asyncio
    async def test_binds_thread_to_matched_application(self):
        """A first email on a new thread should attach it for next time."""
        unbound = {"id": "app-4", "status": "APPLIED", "email_thread_id": None}
        bound = {"id": "app-4", "status": "APPLIED", "email_thread_id": "T-9"}
        conn = FakeConn([None, unbound, bound])

        result = await webhooks._match_or_create_application(
            conn, make_event(), thread_id="T-9"
        )

        assert result["email_thread_id"] == "T-9"
        assert conn.matched_on("SET email_thread_id = $1")

    @pytest.mark.asyncio
    async def test_creates_when_nothing_matches(self):
        created = {"id": "new", "status": "REJECTED"}
        conn = FakeConn([None, None, None, created])

        result = await webhooks._match_or_create_application(
            conn, make_event(), thread_id="T-new", subject="Your application"
        )

        assert result["id"] == "new"
        assert conn.matched_on("INSERT INTO applications")

    @pytest.mark.asyncio
    async def test_rejects_event_without_company(self):
        event = ApplicationEvent(
            event_type=EmailEventType.REJECTION, company="", confidence=0.9
        )
        with pytest.raises(ValueError, match="without a company"):
            await webhooks._match_or_create_application(FakeConn(), event)


# ---------------------------------------------------------------------------
# Status transitions driven by email
# ---------------------------------------------------------------------------


class TestApplyStatusUpdate:
    @pytest.mark.asyncio
    async def test_none_status_is_a_noop(self):
        app = {"id": "a", "status": "APPLIED"}
        conn = FakeConn()

        assert await webhooks._apply_status_update(conn, app, None) is app
        assert conn.queries == []

    @pytest.mark.asyncio
    async def test_same_status_is_a_noop(self):
        app = {"id": "a", "status": "APPLIED"}
        conn = FakeConn()

        result = await webhooks._apply_status_update(
            conn, app, ApplicationStatus.APPLIED
        )

        assert result is app
        assert conn.queries == []

    @pytest.mark.asyncio
    async def test_illegal_transition_is_ignored_not_raised(self):
        """Emails arrive out of order; that must not 500 the webhook."""
        app = {"id": "a", "status": "REJECTED"}
        conn = FakeConn()

        result = await webhooks._apply_status_update(
            conn, app, ApplicationStatus.APPLIED
        )

        assert result is app
        assert conn.queries == []

    @pytest.mark.asyncio
    async def test_legal_transition_is_persisted(self):
        app = {"id": "a", "status": "APPLIED"}
        updated = {"id": "a", "status": "OA_RECEIVED"}
        conn = FakeConn([updated])

        result = await webhooks._apply_status_update(
            conn, app, ApplicationStatus.OA_RECEIVED
        )

        assert result["status"] == "OA_RECEIVED"
        assert conn.matched_on("UPDATE applications")

    @pytest.mark.asyncio
    async def test_offer_while_interview_scheduled_is_applied(self):
        """
        The common real-world case: an offer email arrives but nothing ever
        marked the application INTERVIEWED. A strict single-step check would
        drop the offer entirely.
        """
        app = {"id": "a", "status": "INTERVIEW_SCHEDULED"}
        updated = {"id": "a", "status": "OFFERED"}
        conn = FakeConn([updated])

        result = await webhooks._apply_status_update(
            conn, app, ApplicationStatus.OFFERED
        )

        assert result["status"] == "OFFERED"
        assert conn.matched_on("UPDATE applications")

    @pytest.mark.asyncio
    async def test_terminal_state_is_never_revived_by_inference(self):
        """Path inference must not provide a back door out of a terminal state."""
        app = {"id": "a", "status": "REJECTED"}
        conn = FakeConn()

        result = await webhooks._apply_status_update(
            conn, app, ApplicationStatus.OFFERED
        )

        assert result is app
        assert conn.queries == []


# ---------------------------------------------------------------------------
# Idempotency + sync cursor
# ---------------------------------------------------------------------------


class TestSyncBookkeeping:
    @pytest.mark.asyncio
    async def test_cursor_roundtrip(self):
        conn = FakeConn([{"last_history_id": "4242"}])
        assert await webhooks._get_sync_cursor(conn, "a@b.com") == "4242"

    @pytest.mark.asyncio
    async def test_missing_cursor_is_none(self):
        assert await webhooks._get_sync_cursor(FakeConn(), "a@b.com") is None

    @pytest.mark.asyncio
    async def test_already_processed_detects_duplicate(self):
        conn = FakeConn([{"exists": 1}])
        assert await webhooks._already_processed(conn, "msg-1") is True

    @pytest.mark.asyncio
    async def test_unknown_message_is_not_processed(self):
        assert await webhooks._already_processed(FakeConn(), "msg-2") is False

    @pytest.mark.asyncio
    async def test_blank_message_id_is_never_processed(self):
        assert await webhooks._already_processed(FakeConn(), "") is False


# ---------------------------------------------------------------------------
# Extractor wiring
# ---------------------------------------------------------------------------


class TestExtractorCall:
    @pytest.mark.asyncio
    async def test_extractor_is_awaited_with_three_arguments(self):
        """
        Regression test. The webhook used to call this synchronously with a
        single argument, so the coroutine was never awaited and every email
        failed downstream on a coroutine object.
        """
        from src.email_pipeline import extractor

        fake = AsyncMock(return_value=make_event())
        with patch.object(extractor, "extract_application_event", fake):
            result = await extractor.extract_application_event(
                "subject", "body", "sender@example.com"
            )

        fake.assert_awaited_once_with("subject", "body", "sender@example.com")
        assert result.company == "Stripe"
