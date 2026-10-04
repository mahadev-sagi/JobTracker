"""
JobTracker API — FastAPI application entry-point.

Starts the ASGI app, configures CORS, registers routers, and manages
the database connection pool lifecycle.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.core.config import get_settings
from src.db.database import close_pool, init_pool

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
    yield
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
# CORS
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers fail at startup if an import is broken, rather than silently
# serving an incomplete API.
# ---------------------------------------------------------------------------
from src.api.routes import applications, scraper, webhooks  # noqa: E402

app.include_router(applications.router)
app.include_router(webhooks.router)
app.include_router(scraper.router)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/health", tags=["meta"])
async def health_check() -> dict[str, str]:
    """Lightweight liveness probe used by Docker HEALTHCHECK and load balancers."""
    return {"status": "healthy"}
