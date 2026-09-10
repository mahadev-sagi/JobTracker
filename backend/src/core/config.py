"""
Application configuration via environment variables.

Uses pydantic-settings to load and validate configuration from .env files
and environment variables. A cached singleton is exposed via ``get_settings()``.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration – every field maps to an env var of the same name."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Database ────────────────────────────────────────────────────────
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/jobtracker"

    # ── OpenAI ──────────────────────────────────────────────────────────
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o"

    # ── Google Cloud / Pub-Sub ──────────────────────────────────────────
    GOOGLE_CLOUD_PROJECT_ID: str = ""
    GOOGLE_PUBSUB_TOPIC: str = "gmail-notifications"
    GOOGLE_PUBSUB_SUBSCRIPTION: str = "gmail-notifications-sub"

    # ── Gmail ───────────────────────────────────────────────────────────
    GMAIL_USER_EMAIL: str = ""
    GOOGLE_CREDENTIALS_JSON: str = ""

    # ── URLs ────────────────────────────────────────────────────────────
    LISTINGS_URL: str = ""
    BACKEND_URL: str = "http://localhost:8000"
    FRONTEND_URL: str = "http://localhost:3000"

    # ── Runtime ─────────────────────────────────────────────────────────
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"

    # ── Computed helpers ────────────────────────────────────────────────
    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() == "production"

    @property
    def cors_origins(self) -> list[str]:
        """Return the list of allowed CORS origins."""
        origins = [self.FRONTEND_URL]
        if not self.is_production:
            origins.append("http://localhost:3000")
        # Deduplicate while preserving order
        return list(dict.fromkeys(origins))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton ``Settings`` instance."""
    return Settings()
