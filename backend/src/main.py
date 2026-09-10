"""
JobTracker API — FastAPI application entry-point.

Starts the ASGI app, configures CORS, registers routers, and manages
the database connection pool lifecycle.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

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
# Routers — imported lazily so the module graph stays clean.
# Each router file can be created independently later; the import is
# wrapped in a try/except so the app still boots if a router is missing
# during early development.
# ---------------------------------------------------------------------------
_ROUTERS: list[tuple[str, str, str]] = [
    ("src.api.routes.applications", "router", ""),
    ("src.api.routes.webhooks", "router", ""),
    ("src.api.routes.scraper", "router", ""),
]

for module_path, attr_name, prefix in _ROUTERS:
    try:
        import importlib

        mod = importlib.import_module(module_path)
        router = getattr(mod, attr_name)
        app.include_router(router, prefix=prefix)
        logger.info("Registered router %s", module_path)
    except (ModuleNotFoundError, AttributeError) as exc:
        logger.warning(
            "Skipping router %s – not yet implemented (%s)", module_path, exc
        )


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/health", tags=["meta"])
async def health_check() -> dict[str, str]:
    """Lightweight liveness probe used by Docker HEALTHCHECK and load balancers."""
    return {"status": "healthy"}
