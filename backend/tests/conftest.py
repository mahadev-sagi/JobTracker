"""Shared pytest fixtures."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import asyncpg
import httpx
import pytest
import pytest_asyncio
from cryptography.fernet import Fernet

# Environment variables outrank the developer's .env, which may well say
# ENVIRONMENT=production. Set before anything reads settings.
os.environ.update(
    ENVIRONMENT="test",
    ALLOWED_EMAILS="",
    ADMIN_EMAILS="",
    SCHEDULER_ENABLED="false",
    TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode(),
    PUBSUB_AUDIENCE="",
    PUBSUB_VERIFICATION_TOKEN="test-secret",
    GOOGLE_CLOUD_PROJECT_ID="",
)

from src.api.dependencies import SESSION_COOKIE, get_db
from src.core.config import get_settings
from src.core.security import hash_token, new_token
from src.db.migrate import apply_migrations
from src.email_pipeline import extractor


@pytest.fixture(autouse=True)
def _reset_cached_singletons():
    """Clear process-wide caches between tests.

    The extractor caches its LLM client deliberately: building one per email
    would be wasteful in production. In tests that caching would leak a client
    built before a patch was applied, so every test starts from a clean slate.
    """
    extractor._get_client.cache_clear()
    get_settings.cache_clear()
    yield
    extractor._get_client.cache_clear()
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Real-database fixtures
#
# Tests marked with these fixtures run against an actual Postgres, because
# the bugs that survived longest in this codebase lived in SQL that a fake
# connection happily accepted. Point TEST_DATABASE_URL at a disposable
# database; its public schema is wiped at the start of the session.
# Locally the tests are skipped without it; CI always sets it.
# ---------------------------------------------------------------------------

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")


@pytest.fixture(scope="session")
def _database_schema() -> str:
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL not set")

    async def reset() -> None:
        conn = await asyncpg.connect(TEST_DATABASE_URL)
        try:
            await conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
            await conn.execute("DROP TYPE IF EXISTS application_status")
            await apply_migrations(conn)
        finally:
            await conn.close()

    asyncio.run(reset())
    return TEST_DATABASE_URL


@pytest_asyncio.fixture
async def db(_database_schema) -> AsyncIterator[asyncpg.Connection]:
    conn = await asyncpg.connect(_database_schema)
    await conn.execute(
        "TRUNCATE users, listings, scraper_runs RESTART IDENTITY CASCADE"
    )
    try:
        yield conn
    finally:
        await conn.close()


async def make_user(conn: asyncpg.Connection, email: str = "alice@example.com") -> UUID:
    return await conn.fetchval(
        "INSERT INTO users (google_sub, email) VALUES ($1, $2) RETURNING id",
        f"sub:{email}",
        email,
    )


@dataclass
class Session:
    user_id: UUID
    client: httpx.AsyncClient


@pytest_asyncio.fixture
async def api(db) -> AsyncIterator:
    """Factory for HTTP clients signed in as a given user."""
    from src.main import app

    async def _get_db():
        yield db

    app.dependency_overrides[get_db] = _get_db
    clients: list[httpx.AsyncClient] = []

    async def signed_in(email: str = "alice@example.com") -> Session:
        user_id = await make_user(db, email)
        token = new_token()
        await db.execute(
            "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES ($1, $2, $3)",
            hash_token(token),
            user_id,
            datetime.now(UTC) + timedelta(days=1),
        )
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            cookies={SESSION_COOKIE: token},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        clients.append(client)
        return Session(user_id=user_id, client=client)

    try:
        yield signed_in
    finally:
        for client in clients:
            await client.aclose()
        app.dependency_overrides.clear()
