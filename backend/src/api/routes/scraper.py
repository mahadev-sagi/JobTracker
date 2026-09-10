"""
Scraper trigger router.

Provides endpoints to manually kick off the job-board scraper and to
retrieve the status / results of the most recent run.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, status

from src.core.config import get_settings
from src.scraper.ingestion import run_ingestion

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/scraper", tags=["Scraper"])

# ---------------------------------------------------------------------------
# Module-level state that tracks the latest scraper run.
# In a production system this could be backed by Redis or the database;
# an in-memory dict is fine for a single-process deployment.
# ---------------------------------------------------------------------------

_last_run: dict[str, Any] = {
    "started_at": None,
    "finished_at": None,
    "status": "idle",       # idle | running | completed | failed
    "jobs_found": 0,
    "new_inserted": 0,
    "duplicates_skipped": 0,
    "error": None,
}


async def _run_scraper_task() -> None:
    """
    Wrapper that executes the ingestion pipeline and records results
    in the module-level ``_last_run`` dict.
    """
    global _last_run

    _last_run.update(
        {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
            "status": "running",
            "jobs_found": 0,
            "new_inserted": 0,
            "duplicates_skipped": 0,
            "error": None,
        }
    )

    try:
        result = await run_ingestion()

        _last_run.update(
            {
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "status": "completed",
                "jobs_found": result.get("jobs_found", 0),
                "new_inserted": result.get("new_inserted", 0),
                "duplicates_skipped": result.get("duplicates_skipped", 0),
            }
        )
        logger.info(
            "Scraper run completed – found: %d, inserted: %d, duplicates: %d",
            _last_run["jobs_found"],
            _last_run["new_inserted"],
            _last_run["duplicates_skipped"],
        )

    except Exception as exc:
        _last_run.update(
            {
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "status": "failed",
                "error": str(exc),
            }
        )
        logger.exception("Scraper run failed: %s", exc)


# ---------------------------------------------------------------------------
# POST /run — trigger scraper
# ---------------------------------------------------------------------------


@router.post("/run", status_code=status.HTTP_202_ACCEPTED)
async def trigger_scraper(background_tasks: BackgroundTasks):
    """
    Trigger a manual scraper run.

    The scraper executes as a background task so the caller receives an
    immediate 202 Accepted response. Poll ``GET /status`` to track progress.
    """
    if _last_run["status"] == "running":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A scraper run is already in progress.",
        )

    background_tasks.add_task(_run_scraper_task)

    logger.info("Scraper run triggered manually.")
    return {
        "message": "Scraper run started.",
        "status": "running",
    }


# ---------------------------------------------------------------------------
# GET /status — last run info
# ---------------------------------------------------------------------------


@router.get("/status")
async def get_scraper_status():
    """
    Return the status and statistics of the most recent scraper run.

    Response fields:
    - **started_at**: ISO-8601 timestamp when the run began.
    - **finished_at**: ISO-8601 timestamp when the run ended (``null`` if
      still running).
    - **status**: One of ``idle``, ``running``, ``completed``, ``failed``.
    - **jobs_found**: Total job listings found by the scraper.
    - **new_inserted**: New application rows inserted.
    - **duplicates_skipped**: Listings that already existed.
    - **error**: Error message if the run failed.
    """
    return _last_run
