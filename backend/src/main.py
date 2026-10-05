"""
JobTracker API — FastAPI application entry-point.

Starts the ASGI app, configures CORS, registers routers, and manages
the database connection pool lifecycle.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.core.config import get_settings
from src.db.database import close_pool, get_connection, init_pool
from src.db.migrate import apply_migrations
from src.scheduler import start_scheduler

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
settings = get_settings()
logging.basicConfig(
    level=settings.LOG_LEVEL.upper(),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan: DB pool startup / shutdown
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage resources that live for the entire application lifetime."""
    logger.info("Starting up – initialising database pool …")
    await init_pool()
    async with get_connection() as conn:
        applied = await apply_migrations(conn)
    if applied:
        logger.info("Applied migrations: %s", ", ".join(applied))
    scheduler = start_scheduler()
    yield
    if scheduler is not None:
        scheduler.cancel()
    logger.info("Shutting down – closing database pool …")
    await close_pool()


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------
app = FastAPI(
    title="JobTracker API",
    version="0.1.0",
    description=(
        "Backend API for the JobTracker application. "
        "Tracks job applications, ingests Gmail notifications via "
        "Google Pub/Sub webhooks, and scrapes new listings."
    ),
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# Cross-site request forgery
# ---------------------------------------------------------------------------
# The UI and API share one origin (nginx proxies /api), so no CORS is
# configured and browsers refuse cross-origin requests that carry a custom
# header. Requiring one on every state-changing call means another site cannot
# make a signed-in user's browser create, edit or delete anything, whatever
# the cookie's SameSite handling. Pub/Sub is exempt: it authenticates with a
# bearer token, not the cookie.
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_CSRF_EXEMPT_PREFIX = "/api/webhooks/"


@app.middleware("http")
async def require_same_origin_header(request: Request, call_next):
    if (
        request.method not in _SAFE_METHODS
        and request.url.path.startswith("/api/")
        and not request.url.path.startswith(_CSRF_EXEMPT_PREFIX)
        and request.headers.get("x-requested-with") != "XMLHttpRequest"
    ):
        return JSONResponse({"detail": "Missing X-Requested-With header."}, status_code=403)
    return await call_next(request)


# ---------------------------------------------------------------------------
# Routers fail at startup if an import is broken, rather than silently
# serving an incomplete API.
# ---------------------------------------------------------------------------
from src.api.routes import (  # noqa: E402
    applications,
    auth,
    gmail,
    listings,
    scraper,
    webhooks,
)

app.include_router(auth.router)
app.include_router(applications.router)
app.include_router(listings.router)
app.include_router(gmail.router)
app.include_router(webhooks.router)
app.include_router(scraper.router)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/health", tags=["meta"])
async def health_check() -> dict[str, str]:
    """Lightweight liveness probe used by Docker HEALTHCHECK and load balancers."""
    return {"status": "healthy"}
