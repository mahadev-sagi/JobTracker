"""
In-process periodic jobs: Gmail watch renewal and scheduled scraping.

These used to be planned as AWS Lambda + EventBridge. On a single server an
asyncio loop does the same with nothing extra to deploy. Each job takes a
Postgres advisory lock, so running several uvicorn workers is still safe:
only one of them does the work each tick.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from asyncpg import Connection

from src.api.routes.scraper import ScraperBusyError, execute_run, start_run
from src.core.config import get_settings
from src.db.database import get_connection
from src.email_pipeline.accounts import renew_expiring_watches

logger = logging.getLogger(__name__)

TICK_SECONDS = 3600

_WATCH_LOCK = 7_314_202_602
_SCRAPER_LOCK = 7_314_202_603


async def _with_lock(lock_id: int, job: Callable[[Connection], Awaitable[None]]) -> None:
    async with get_connection() as conn:
        if not await conn.fetchval("SELECT pg_try_advisory_lock($1)", lock_id):
            return
        try:
            await job(conn)
        finally:
            await conn.execute("SELECT pg_advisory_unlock($1)", lock_id)


async def _renew_watches(conn: Connection) -> None:
    renewed = await renew_expiring_watches(conn)
    if renewed:
        logger.info("Renewed %d Gmail watch(es)", renewed)


async def _scrape_if_due(conn: Connection) -> None:
    hours = get_settings().SCRAPER_INTERVAL_HOURS
    if hours <= 0:
        return
    due = await conn.fetchval(
        """
        SELECT NOT EXISTS (
            SELECT 1 FROM scraper_runs
            WHERE started_at > NOW() - make_interval(hours => $1)
        )
        """,
        hours,
    )
    if not due:
        return
    try:
        run_id = await start_run(conn, "scheduled")
    except ScraperBusyError:
        return
    await execute_run(run_id)


async def _loop() -> None:
    while True:
        for name, lock_id, job in (
            ("watch renewal", _WATCH_LOCK, _renew_watches),
            ("scheduled scrape", _SCRAPER_LOCK, _scrape_if_due),
        ):
            try:
                await _with_lock(lock_id, job)
            except Exception:
                logger.exception("Scheduled %s failed", name)
        await asyncio.sleep(TICK_SECONDS)


def start_scheduler() -> asyncio.Task | None:
    if not get_settings().SCHEDULER_ENABLED:
        return None
    return asyncio.create_task(_loop(), name="scheduler")
