"""
AWS Lambda handler for scheduled job-listing scraping.

This function is invoked on a schedule by Amazon EventBridge (CloudWatch Events)
to trigger the JobTracker scraper.

Architecture:
    EventBridge (cron) -> This Lambda -> Backend API /api/scraper/run

Environment Variables:
    BACKEND_API_URL : Base URL of the JobTracker backend.
    API_SECRET_KEY  : Shared secret for authenticating scraper requests.
    SCRAPER_MODE    : "api" (default) to call the backend, or "direct" for
                      in-process scraping (requires scraper code in layer).
    LISTINGS_URL    : URL of the job-listings page to scrape (direct mode only).
    LOG_LEVEL       : Logging verbosity (default: INFO).
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any
from urllib import request, error

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BACKEND_API_URL: str = os.environ.get("BACKEND_API_URL", "http://localhost:8000")
API_SECRET_KEY: str = os.environ.get("API_SECRET_KEY", "")
SCRAPER_MODE: str = os.environ.get("SCRAPER_MODE", "api")
LISTINGS_URL: str = os.environ.get("LISTINGS_URL", "")
LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO")

logger = logging.getLogger("scraper_cron")
logger.setLevel(LOG_LEVEL)

if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(
        logging.Formatter("[%(levelname)s] %(asctime)s %(name)s — %(message)s")
    )
    logger.addHandler(_handler)


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

EventBridgeEvent = dict[str, Any]
LambdaContext = Any


# ---------------------------------------------------------------------------
# Scraping strategies
# ---------------------------------------------------------------------------


def _run_via_api() -> dict[str, Any]:
    """Trigger the scraper by calling the backend REST API."""
    url = f"{BACKEND_API_URL.rstrip('/')}/api/scraper/run"
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if API_SECRET_KEY:
        headers["X-Api-Secret"] = API_SECRET_KEY

    payload = json.dumps({"source": "lambda_cron"}).encode("utf-8")
    req = request.Request(url, data=payload, headers=headers, method="POST")

    logger.info("Triggering scraper via API: %s", url)

    try:
        with request.urlopen(req, timeout=120) as resp:
            body = resp.read().decode("utf-8")
            logger.info("Backend responded with status %d", resp.status)
            return json.loads(body) if body else {}
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Backend HTTP {exc.code}: {body}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Cannot reach backend at {url}: {exc.reason}") from exc


def _run_direct() -> dict[str, Any]:
    """Run scraping directly inside the Lambda (placeholder)."""
    logger.info("Direct scraping mode — target URL: %s", LISTINGS_URL)

    if not LISTINGS_URL:
        raise ValueError("LISTINGS_URL environment variable is required for direct mode")

    # TODO: Import shared scraper module from Lambda Layer and run:
    #   from jobtracker.scraper import scrape_listings
    #   results = scrape_listings(LISTINGS_URL)
    logger.warning("Direct scraping not yet implemented — returning placeholder")
    return {
        "mode": "direct",
        "listings_url": LISTINGS_URL,
        "jobs_found": 0,
        "message": "Direct scraping placeholder — implement with Lambda Layer",
    }


# ---------------------------------------------------------------------------
# Lambda entry point
# ---------------------------------------------------------------------------


def handler(event: EventBridgeEvent, context: LambdaContext) -> dict[str, Any]:
    """AWS Lambda handler for scheduled scraper invocations.

    Args:
        event:   EventBridge scheduled event payload.
        context: Lambda runtime context.

    Returns:
        Execution summary including timing, mode, and results.
    """
    request_id = getattr(context, "aws_request_id", "local")
    remaining_ms = getattr(context, "get_remaining_time_in_millis", lambda: -1)()

    logger.info(
        "Scraper cron invoked — requestId=%s remainingMs=%d mode=%s",
        request_id,
        remaining_ms,
        SCRAPER_MODE,
    )
    logger.debug("Event payload: %s", json.dumps(event, default=str))

    start = time.monotonic()
    status = "success"
    error_message: str | None = None
    result: dict[str, Any] = {}

    try:
        if SCRAPER_MODE == "direct":
            result = _run_direct()
        else:
            result = _run_via_api()

    except (RuntimeError, ValueError) as exc:
        status = "error"
        error_message = str(exc)
        logger.error("Scraper failed: %s", exc)

    except Exception as exc:  # noqa: BLE001
        status = "error"
        error_message = f"Unexpected error: {exc}"
        logger.exception("Unexpected error during scraper execution")

    elapsed_ms = round((time.monotonic() - start) * 1000, 2)

    summary: dict[str, Any] = {
        "status": status,
        "mode": SCRAPER_MODE,
        "elapsed_ms": elapsed_ms,
        "request_id": request_id,
        "result": result,
    }
    if error_message:
        summary["error"] = error_message

    logger.info("Scraper finished — %s", json.dumps(summary, default=str))
    return summary
