"""Historical scans preserve inbox cursors and release the shared mailbox lock."""

from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from src.email_pipeline.backfill import run_scan


@pytest.mark.asyncio
async def test_scan_uses_selected_date_and_scope_and_preserves_cursor():
    scan_id, user_id = uuid4(), uuid4()
    conn = AsyncMock()
    conn.fetchval.return_value = True
    conn.fetchrow.side_effect = [
        {"start_date": date(2026, 9, 1), "inbox_only": False},
        {"status": "active"},
    ]
    gmail = AsyncMock()
    gmail.get_messages_after.return_value = [{"id": "a"}, {"id": "b"}, {"id": "c"}]

    @asynccontextmanager
    async def connection():
        yield conn

    with (
        patch("src.email_pipeline.backfill.get_connection", connection),
        patch("src.email_pipeline.backfill.gmail_for_account", return_value=gmail),
        patch("src.email_pipeline.backfill._process_message", new_callable=AsyncMock) as process,
    ):
        process.side_effect = ["updated", "duplicate", ValueError("classifier unavailable")]
        await run_scan(scan_id, user_id)

    since = int(datetime(2026, 9, 1, tzinfo=UTC).timestamp()) - 1
    gmail.get_messages_after.assert_awaited_once_with(since, inbox_only=False)
    assert process.await_count == 3
    queries = [call.args[0] for call in conn.execute.await_args_list]
    assert any("errors = errors + 1" in query for query in queries)
    assert any("'partial'" in query for query in queries)
    assert not any("last_history_id" in query for query in queries)
    assert "pg_advisory_unlock" in queries[-1]


@pytest.mark.asyncio
async def test_busy_mailbox_does_not_process_or_unlock_another_scan():
    conn = AsyncMock()
    conn.fetchval.return_value = False

    @asynccontextmanager
    async def connection():
        yield conn

    with (
        patch("src.email_pipeline.backfill.get_connection", connection),
        patch("src.email_pipeline.backfill._process_message", new_callable=AsyncMock) as process,
    ):
        await run_scan(uuid4(), uuid4())
    process.assert_not_awaited()
    assert not any("pg_advisory_unlock" in call.args[0] for call in conn.execute.await_args_list)
    assert "'failed'" in conn.execute.await_args.args[0]
