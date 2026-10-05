"""
Schema migration runner.

Applies every ``migrations/*.sql`` not yet recorded in ``schema_migrations``,
in filename order, each in its own transaction. Runs at application startup.

This replaces mounting the directory into the Postgres entrypoint, which only
ran the files once when the data volume was first created, so any later
migration had to be applied by hand against an existing database.
"""

from __future__ import annotations

import logging
from pathlib import Path

import asyncpg

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

# Arbitrary constant. Every backend worker runs this at startup; the advisory
# lock makes the others wait instead of applying the same file concurrently.
_LOCK_ID = 7_314_202_601


async def apply_migrations(conn: asyncpg.Connection) -> list[str]:
    """Apply pending migrations and return the names of those applied."""
    applied_now: list[str] = []
    await conn.execute("SELECT pg_advisory_lock($1)", _LOCK_ID)
    try:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                name       VARCHAR(255) PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        done = {
            row["name"]
            for row in await conn.fetch("SELECT name FROM schema_migrations")
        }
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.name in done:
                continue
            logger.info("Applying migration %s", path.name)
            async with conn.transaction():
                await conn.execute(path.read_text(encoding="utf-8"))
                await conn.execute(
                    "INSERT INTO schema_migrations (name) VALUES ($1)", path.name
                )
            applied_now.append(path.name)
    finally:
        await conn.execute("SELECT pg_advisory_unlock($1)", _LOCK_ID)
    return applied_now
