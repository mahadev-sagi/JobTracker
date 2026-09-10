"""
Parser for SimplifyJobs listings.json format.

Converts the raw JSON array into a list of ``ApplicationCreate``
Pydantic objects ready for database insertion.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from src.db.models import ApplicationCreate

logger = logging.getLogger(__name__)


def parse_listings(raw_json: list[dict]) -> list[ApplicationCreate]:
    """
    Transform raw SimplifyJobs listing dicts into ``ApplicationCreate`` models.

    Behaviour:
    - Skips entries where ``is_active`` is explicitly ``False``.
    - Joins the ``locations`` list into a comma-separated string.
    - Converts the ``date_posted`` Unix timestamp (seconds) to a
      timezone-aware ``datetime``.
    - Gracefully handles missing or malformed fields by logging a
      warning and skipping the entry.

    Parameters
    ----------
    raw_json:
        A list of dicts as decoded from the SimplifyJobs
        ``listings.json`` file.

    Returns
    -------
    list[ApplicationCreate]
    """
    results: list[ApplicationCreate] = []

    for idx, entry in enumerate(raw_json):
        # ── Skip inactive ────────────────────────────────────────
        if entry.get("is_active") is False:
            continue

        try:
            company = entry.get("company_name") or ""
            role = entry.get("title") or ""

            if not company or not role:
                logger.warning(
                    "Listing %d missing company_name or title — skipped.", idx
                )
                continue

            # Locations may be a list, a single string, or absent.
            locations_raw = entry.get("locations")
            if isinstance(locations_raw, list):
                location = ", ".join(str(loc) for loc in locations_raw if loc)
            elif isinstance(locations_raw, str):
                location = locations_raw
            else:
                location = None

            # URL
            url = entry.get("url") or None

            # Date — Unix timestamp in *seconds*
            date_posted: datetime | None = None
            ts = entry.get("date_posted")
            if ts is not None:
                try:
                    date_posted = datetime.fromtimestamp(
                        float(ts), tz=timezone.utc
                    )
                except (ValueError, TypeError, OSError):
                    logger.warning(
                        "Listing %d has invalid date_posted=%r — ignored.", idx, ts
                    )

            results.append(
                ApplicationCreate(
                    company=company,
                    role=role,
                    location=location or None,
                    url=url,
                    date_posted=date_posted,
                    source="SIMPLIFY_SCRAPER",
                )
            )

        except Exception:
            logger.exception("Failed to parse listing at index %d", idx)

    logger.info(
        "Parsed %d active listings from %d total entries.", len(results), len(raw_json)
    )
    return results
