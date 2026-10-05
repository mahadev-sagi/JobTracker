"""
Scraper trigger router.

Runs are recorded in ``scraper_runs``, so progress survives restarts and is
consistent across uvicorn workers. A partial unique index on that table
guarantees at most one run in flight.
"""

from __future__ import annotations

import logging

from asyncpg import Connection
from asyncpg.exceptions import UniqueViolationError
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from src.api.dependencies import CurrentUser, get_current_user, get_db, require_admin
from src.db.database import get_connection
from src.scraper.ingestion import run_ingestion

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/scraper", tags=["Scraper"])


class ScraperBusyError(RuntimeError):
    pass


async def start_run(conn: Connection, trigger: str) -> int:
    """Record a new run, or raise ``ScraperBusyError`` if one is in flight."""
    # A restart mid-run leaves a 'running' row that would otherwise block
    # every future run. A real run takes minutes, so an hour-old one is dead.
    await conn.execute(
        """
        UPDATE scraper_runs
        SET status = 'failed', finished_at = NOW(), error = 'Did not finish; interrupted.'
        WHERE status = 'running' AND started_at < NOW() - INTERVAL '1 hour'
        """
    )
    try:
        return await conn.fetchval(
            "INSERT INTO scraper_runs (trigger, status) VALUES ($1, 'running') RETURNING id",
            trigger,
        )
    except UniqueViolationError as exc:
        raise ScraperBusyError from exc


async def execute_run(run_id: int) -> None:
    """Run ingestion and record the outcome against ``run_id``."""
    try:
        result = await run_ingestion()
    except Exception as exc:
        logger.exception("Scraper run %s failed", run_id)
        async with get_connection() as conn:
            await conn.execute(
                """
                UPDATE scraper_runs SET status = 'failed', finished_at = NOW(), error = $2
                WHERE id = $1
                """,
                run_id,
                str(exc)[:1000],
            )
        return

    # run_ingestion() reports fetch failures through its error counter
    # rather than raising.
    failed = result.get("errors", 0) > 0 and result.get("total_found", 0) == 0
    async with get_connection() as conn:
        await conn.execute(
            """
            UPDATE scraper_runs
            SET status = $2, finished_at = NOW(), jobs_found = $3,
                new_inserted = $4, duplicates_skipped = $5, error = $6
            WHERE id = $1
            """,
            run_id,
            "failed" if failed else "completed",
            result.get("total_found", 0),
            result.get("new_inserted", 0),
            result.get("duplicates_skipped", 0),
            "Could not fetch listings." if failed else None,
        )
    logger.info("Scraper run %s finished: %s", run_id, result)


@router.post("/run", status_code=status.HTTP_202_ACCEPTED)
async def trigger_scraper(
    background_tasks: BackgroundTasks,
    _admin: CurrentUser = Depends(require_admin),
    conn: Connection = Depends(get_db),
):
    """Start a scraper run in the background. Poll ``GET /status``."""
    try:
        run_id = await start_run(conn, "manual")
    except ScraperBusyError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A scraper run is already in progress."
        ) from exc
    background_tasks.add_task(execute_run, run_id)
    return {"message": "Scraper run started.", "status": "running", "id": run_id}


@router.get("/status")
async def get_scraper_status(
    _user: CurrentUser = Depends(get_current_user),
    conn: Connection = Depends(get_db),
):
    """The most recent run, or an idle placeholder if none has happened."""
    row = await conn.fetchrow("SELECT * FROM scraper_runs ORDER BY started_at DESC LIMIT 1")
    if row is None:
        return {"status": "idle"}
    return dict(row)
