"""Shared pytest fixtures."""

from __future__ import annotations

import pytest
from src.core.config import get_settings
from src.email_pipeline import extractor, gmail_service


@pytest.fixture(autouse=True)
def _reset_cached_singletons():
    """Clear process-wide caches between tests.

    The extractor caches its LLM client and the Gmail service is a module-level
    singleton, both deliberately: building either per email would be wasteful
    in production. In tests that caching would leak a client built before a
    patch was applied, so every test starts from a clean slate.
    """
    extractor._get_client.cache_clear()
    gmail_service.reset_gmail_service()
    get_settings.cache_clear()
    yield
    extractor._get_client.cache_clear()
    gmail_service.reset_gmail_service()
    get_settings.cache_clear()
