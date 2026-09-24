"""
Tests for the scraper parser and ingestion pipeline.

Parser tests exercise real parsing logic; ingestion tests mock both
the HTTP fetch and the database connection pool.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.db.models import ApplicationCreate
from src.scraper.parser import parse_listings

# ═══════════════════════════════════════════════════════════════════
#  Parser tests
# ═══════════════════════════════════════════════════════════════════


SAMPLE_LISTINGS: list[dict] = [
    {
        "company_name": "Google",
        "title": "Software Engineer Intern",
        "locations": ["Mountain View, CA", "New York, NY"],
        "url": "https://careers.google.com/jobs/123",
        "date_posted": 1_700_000_000,
        "is_active": True,
    },
    {
        "company_name": "Meta",
        "title": "Data Scientist",
        "locations": ["Menlo Park, CA"],
        "url": "https://meta.com/careers/456",
        "date_posted": 1_700_100_000,
        "is_active": True,
    },
    {
        "company_name": "OldCorp",
        "title": "Analyst",
        "locations": [],
        "url": "https://oldcorp.com/jobs/789",
        "date_posted": 1_690_000_000,
        "is_active": False,  # should be filtered out
    },
]


class TestParser:
    """Tests for ``parse_listings``."""

    def test_parse_sample_listings(self):
        """Active listings are correctly converted to ApplicationCreate objects."""
        results = parse_listings(SAMPLE_LISTINGS)
        assert len(results) == 2

        google = results[0]
        assert isinstance(google, ApplicationCreate)
        assert google.company == "Google"
        assert google.role == "Software Engineer Intern"
        assert google.location == "Mountain View, CA, New York, NY"
        assert google.url == "https://careers.google.com/jobs/123"
        assert google.source == "SIMPLIFY_SCRAPER"
        assert google.date_posted is not None
        expected_date = datetime.fromtimestamp(1_700_000_000, tz=UTC).date()
        assert google.date_posted == expected_date

    def test_inactive_listings_filtered_out(self):
        """Listings with is_active == False are excluded."""
        results = parse_listings(SAMPLE_LISTINGS)
        companies = [r.company for r in results]
        assert "OldCorp" not in companies

    def test_missing_company_or_title_skipped(self):
        """Entries lacking company_name or title are skipped gracefully."""
        bad_entries = [
            {"company_name": "", "title": "Dev", "is_active": True},
            {"company_name": "Acme", "title": "", "is_active": True},
            {"is_active": True},
        ]
        results = parse_listings(bad_entries)
        assert len(results) == 0

    def test_location_handling(self):
        """Locations as list, string, or missing are handled properly."""
        entries = [
            {"company_name": "A", "title": "T", "locations": ["SF", "NYC"], "is_active": True},
            {"company_name": "B", "title": "T", "locations": "Remote", "is_active": True},
            {"company_name": "C", "title": "T", "locations": None, "is_active": True},
        ]
        results = parse_listings(entries)
        assert results[0].location == "SF, NYC"
        assert results[1].location == "Remote"
        assert results[2].location is None

    def test_invalid_date_posted(self):
        """Non-numeric date_posted values are ignored without crashing."""
        entries = [
            {
                "company_name": "A",
                "title": "T",
                "date_posted": "not-a-timestamp",
                "is_active": True,
            },
        ]
        results = parse_listings(entries)
        assert len(results) == 1
        assert results[0].date_posted is None

    def test_empty_input(self):
        """An empty list returns an empty list."""
        assert parse_listings([]) == []


# ═══════════════════════════════════════════════════════════════════
#  Ingestion pipeline tests
# ═══════════════════════════════════════════════════════════════════


class TestIngestion:
    """Tests for ``run_ingestion`` with mocked HTTP and DB."""

    @pytest.mark.asyncio
    async def test_run_ingestion_success(self):
        """Happy-path: fetch → parse → upsert produces correct stats."""
        from src.scraper.ingestion import run_ingestion

        mock_response = MagicMock()
        mock_response.json.return_value = SAMPLE_LISTINGS[:2]  # 2 active
        mock_response.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.get = AsyncMock(return_value=mock_response)

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="INSERT 0 1")

        @asynccontextmanager
        async def mock_transaction():
            yield

        mock_conn.transaction = mock_transaction

        @asynccontextmanager
        async def mock_get_conn():
            yield mock_conn

        with (
            patch("src.scraper.ingestion.httpx.AsyncClient", return_value=mock_http),
            patch("src.scraper.ingestion.get_connection", mock_get_conn),
        ):
            stats = await run_ingestion()

        assert stats["total_found"] == 2
        assert stats["new_inserted"] == 2
        assert stats["duplicates_skipped"] == 0
        assert stats["errors"] == 0

    @pytest.mark.asyncio
    async def test_run_ingestion_http_error(self):
        """When the HTTP fetch fails, errors=1 and nothing else changes."""
        import httpx as _httpx
        from src.scraper.ingestion import run_ingestion

        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.get = AsyncMock(
            side_effect=_httpx.HTTPStatusError(
                "404",
                request=MagicMock(),
                response=MagicMock(status_code=404),
            )
        )

        with patch(
            "src.scraper.ingestion.httpx.AsyncClient",
            return_value=mock_http,
        ):
            stats = await run_ingestion()

        assert stats["errors"] == 1
        assert stats["new_inserted"] == 0

    @pytest.mark.asyncio
    async def test_run_ingestion_duplicates(self):
        """Duplicate rows (INSERT 0 0) are counted as duplicates_skipped."""
        from src.scraper.ingestion import run_ingestion

        mock_response = MagicMock()
        mock_response.json.return_value = SAMPLE_LISTINGS[:1]
        mock_response.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.get = AsyncMock(return_value=mock_response)

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="INSERT 0 0")

        @asynccontextmanager
        async def mock_transaction():
            yield

        mock_conn.transaction = mock_transaction

        @asynccontextmanager
        async def mock_get_conn():
            yield mock_conn

        with (
            patch("src.scraper.ingestion.httpx.AsyncClient", return_value=mock_http),
            patch("src.scraper.ingestion.get_connection", mock_get_conn),
        ):
            stats = await run_ingestion()

        assert stats["total_found"] == 1
        assert stats["new_inserted"] == 0
        assert stats["duplicates_skipped"] == 1
