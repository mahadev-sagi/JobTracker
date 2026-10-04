"""Exercise authentication and retry behavior through the actual HTTP routes."""

import base64
import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from src.api.dependencies import get_db
from src.api.routes import webhooks
from src.core.config import Settings, get_settings
from src.main import app


@pytest.fixture
def connection():
    conn = AsyncMock()
    conn.transaction = MagicMock(return_value=AsyncMock())
    app.dependency_overrides[get_db] = lambda: conn
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, PUBSUB_VERIFICATION_TOKEN="test-secret"
    )
    yield conn
    app.dependency_overrides.clear()


def payload():
    data = base64.b64encode(json.dumps({
        "emailAddress": "test@example.com", "historyId": "200"
    }).encode()).decode()
    return {"message": {"data": data}}


@pytest.mark.asyncio
@pytest.mark.parametrize("token", [None, "wrong"])
async def test_webhook_rejects_unauthenticated_delivery(connection, token):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/webhooks/gmail", json=payload(), headers=headers)
    assert response.status_code == 401
    connection.fetchrow.assert_not_awaited()


@pytest.mark.asyncio
async def test_webhook_fails_closed_without_configuration(connection):
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/webhooks/gmail", json=payload())
    assert response.status_code == 503


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["history", "extraction", "update", None])
async def test_delivery_retry_preserves_cursor_and_unprocessed_message(connection, monkeypatch, failure):
    monkeypatch.setattr(webhooks, "_get_sync_cursor", AsyncMock(return_value="100"))
    save = AsyncMock()
    mark = AsyncMock()
    monkeypatch.setattr(webhooks, "_save_sync_cursor", save)
    monkeypatch.setattr(webhooks, "_mark_processed", mark)
    monkeypatch.setattr(webhooks, "_already_processed", AsyncMock(return_value=False))
    gmail = AsyncMock()
    gmail.get_new_messages.return_value = [{"id": "message-1", "threadId": "thread-1"}]
    gmail.get_message_content.return_value = ("subject", "body", "sender")
    if failure == "history":
        gmail.get_new_messages.side_effect = RuntimeError("Gmail unavailable")
    monkeypatch.setattr(webhooks, "get_gmail_service", lambda: gmail)
    event = webhooks.ApplicationEvent(
        event_type="REJECTION", company="Example", role="Engineer", confidence=0.95
    )
    extract = AsyncMock(return_value=event)
    if failure == "extraction":
        extract.side_effect = RuntimeError("LLM unavailable")
    monkeypatch.setattr(webhooks, "extract_application_event", extract)
    monkeypatch.setattr(webhooks, "_match_or_create_application", AsyncMock(return_value={"id": "app"}))
    update = AsyncMock()
    if failure == "update":
        update.side_effect = RuntimeError("Database unavailable")
    monkeypatch.setattr(webhooks, "_apply_status_update", update)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/webhooks/gmail", json=payload(), headers={"Authorization": "Bearer test-secret"}
        )
    if failure:
        assert response.status_code == 503
        save.assert_not_awaited()
        mark.assert_not_awaited()
    else:
        assert response.status_code == 200
        mark.assert_awaited_once_with(connection, "message-1", "thread-1")
        save.assert_awaited_once_with(connection, "test@example.com", "200")
