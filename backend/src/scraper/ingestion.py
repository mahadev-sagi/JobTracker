"""
Scraper ingestion pipeline.

Fetches job listings from the configured remote URL, parses them,
and bulk-upserts into the shared PostgreSQL ``listings`` table using
INSERT … ON CONFLICT DO NOTHING via asyncpg.
"""

from __future__ import annotations

import logging

import httpx

from src.core.config import get_settings
from src.db.database import get_connection
from src.scraper.parser import parse_listings

logger = logging.getLogger(__name__)


async def run_ingestion() -> dict[str, int]:
    """
    End-to-end ingestion: fetch → parse → upsert.

    Returns
    -------
    dict[str, int]
        Summary counters::

            {
                "total_found":       <int>,
                "new_inserted":      <int>,
                "duplicates_skipped": <int>,
                "errors":            <int>,
            }
    """
    settings = get_settings()
    stats: dict[str, int] = {
        "total_found": 0,
        "new_inserted": 0,
        "duplicates_skipped": 0,
        "errors": 0,
    }

    # ── 1. Fetch ─────────────────────────────────────────────────────
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(settings.LISTINGS_URL)
            response.raise_for_status()
            raw_json: list[dict] = response.json()
    except httpx.HTTPError:
        logger.exception("Failed to fetch listings from %s", settings.LISTINGS_URL)
        stats["errors"] += 1
        return stats
    except ValueError:
        logger.exception("Listings response was not valid JSON.")
        stats["errors"] += 1
        return stats

    # ── 2. Parse ─────────────────────────────────────────────────────
    listings = parse_listings(raw_json)
    stats["total_found"] = len(listings)

    if not listings:
        logger.info("No active listings found — nothing to ingest.")
        return stats

    # ── 3. Upsert ────────────────────────────────────────────────────
    upsert_sql = """
        INSERT INTO listings (company, role, location, url, date_posted, source)
        VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT DO NOTHING
    """

    try:
        async with get_connection() as conn:
            async with conn.transaction():
                for listing in listings:
                    try:
                        result = await conn.execute(
                            upsert_sql,
                            listing.company,
                            listing.role,
                            listing.location,
                            listing.url,
                            listing.date_posted,
                            listing.source,
                        )
                        # asyncpg returns 'INSERT 0 1' if inserted, 'INSERT 0 0' if conflict
                        if result.endswith("1"):
                            stats["new_inserted"] += 1
                        else:
                            stats["duplicates_skipped"] += 1
                    except Exception:
                        logger.exception(
                            "Error upserting listing company=%s role=%s",
                            listing.company,
                            listing.role,
                        )
                        stats["errors"] += 1
    except Exception:
        logger.exception("Database connection error during ingestion")
        stats["errors"] += 1

    logger.info(
        "Ingestion complete — total=%d new=%d dupes=%d errors=%d",
        stats["total_found"],
        stats["new_inserted"],
        stats["duplicates_skipped"],
        stats["errors"],
    )
    return stats
