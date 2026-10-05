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

    # ── Google OAuth (sign-in and Gmail access) ─────────────────────────
    # A "Web application" OAuth client. Register two redirect URIs on it:
    # {PUBLIC_URL}/api/auth/callback and {PUBLIC_URL}/api/gmail/callback.
    GOOGLE_OAUTH_CLIENT_ID: str = ""
    GOOGLE_OAUTH_CLIENT_SECRET: str = ""

    # Fernet key encrypting stored Gmail refresh tokens. Generate with:
    # python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # Changing it makes every stored token unreadable; users must reconnect.
    TOKEN_ENCRYPTION_KEY: str = ""

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

    # ── Access control ──────────────────────────────────────────────────
    # Comma-separated. Only these addresses (plus admins) may sign in. Empty
    # admits anyone in development and no one in production.
    ALLOWED_EMAILS: str = ""
    # Comma-separated. Admins may trigger the scraper and are always allowed.
    ADMIN_EMAILS: str = ""
    SESSION_TTL_DAYS: int = 30
    # Development only: exposes /api/auth/dev-login so the app can be used
    # without a Google OAuth client. Ignored in production.
    DEV_LOGIN_ENABLED: bool = False

    # ── Background jobs ─────────────────────────────────────────────────
    SCHEDULER_ENABLED: bool = True
    # 0 disables scheduled scraping; an admin can still run it by hand.
    SCRAPER_INTERVAL_HOURS: int = 24

    # ── URLs ────────────────────────────────────────────────────────────
    LISTINGS_URL: str = ""
    # Where users reach the app, without a trailing slash. OAuth redirect URIs
    # are built from it, and an https:// value marks cookies Secure.
    PUBLIC_URL: str = "http://localhost:5173"

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
    def public_url(self) -> str:
        return self.PUBLIC_URL.rstrip("/")

    @property
    def secure_cookies(self) -> bool:
        return self.public_url.startswith("https://")

    @property
    def pubsub_topic(self) -> str | None:
        """Fully qualified topic Gmail publishes to, or None if unconfigured."""
        if not self.GOOGLE_CLOUD_PROJECT_ID or not self.GOOGLE_PUBSUB_TOPIC:
            return None
        return f"projects/{self.GOOGLE_CLOUD_PROJECT_ID}/topics/{self.GOOGLE_PUBSUB_TOPIC}"

    @property
    def admin_emails(self) -> set[str]:
        return _email_set(self.ADMIN_EMAILS)

    def may_sign_in(self, email: str) -> bool:
        allowed = _email_set(self.ALLOWED_EMAILS) | self.admin_emails
        if not allowed:
            # Gmail access makes an open sign-up a liability, so production
            # never defaults to it.
            return not self.is_production
        return email.lower() in allowed

    @property
    def dev_login_enabled(self) -> bool:
        return self.DEV_LOGIN_ENABLED and not self.is_production


def _email_set(raw: str) -> set[str]:
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton ``Settings`` instance."""
    return Settings()
