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

    # ── LLM (any OpenAI-compatible endpoint) ────────────────────────────
    # Defaults target Google's Gemini compatibility layer, whose free tier is
    # ample for this workload. Structured outputs via the SDK's strict
    # `.parse()` helper are supported there, so no provider-specific code is
    # needed — point these three at OpenAI, Groq or anything else to switch.
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    # flash-lite carries a far higher free-tier request quota than full flash.
    LLM_MODEL: str = "gemini-3.1-flash-lite"

    # ── OpenAI (legacy aliases) ─────────────────────────────────────────
    # Retained so existing .env files keep working; LLM_* takes precedence.
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = ""

    # ── Google Cloud / Pub-Sub ──────────────────────────────────────────
    GOOGLE_CLOUD_PROJECT_ID: str = ""
    GOOGLE_PUBSUB_TOPIC: str = "gmail-notifications"
    GOOGLE_PUBSUB_SUBSCRIPTION: str = "gmail-notifications-sub"

    # ── Gmail ───────────────────────────────────────────────────────────
    GMAIL_USER_EMAIL: str = ""
    GOOGLE_CREDENTIALS_JSON: str = ""

    # ── Pub/Sub push authentication ─────────────────────────────────────
    # Preferred: configure the push subscription with an OIDC token and set
    # PUBSUB_AUDIENCE to the value you gave it. The webhook then verifies a
    # real Google-signed JWT.
    PUBSUB_AUDIENCE: str = ""
    # Optional extra check: the service account the subscription pushes as.
    PUBSUB_SERVICE_ACCOUNT_EMAIL: str = ""
    # Fallback for local development: a plain shared secret sent as a bearer
    # token. Ignored when PUBSUB_AUDIENCE is set.
    PUBSUB_VERIFICATION_TOKEN: str = ""

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
    def llm_api_key(self) -> str:
        """Resolved LLM credential, preferring LLM_API_KEY over the alias."""
        return self.LLM_API_KEY or self.OPENAI_API_KEY

    @property
    def llm_model(self) -> str:
        """Resolved model name, preferring LLM_MODEL over the alias."""
        return self.LLM_MODEL or self.OPENAI_MODEL

    @property
    def llm_base_url(self) -> str | None:
        """Base URL for the LLM endpoint, or None to use the SDK default."""
        return self.LLM_BASE_URL or None

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
