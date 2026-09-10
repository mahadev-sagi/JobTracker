"""
Pydantic data models for the ``applications`` domain.

These are *not* ORM models — they are pure Pydantic schemas used for
validation, serialization, and API documentation.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from src.core.state_machine import ApplicationStatus


# ── Base schema ─────────────────────────────────────────────────────────
class ApplicationBase(BaseModel):
    """Fields shared by creation and read schemas."""

    company: str = Field(..., min_length=1, max_length=255, examples=["Google"])
    role: str = Field(..., min_length=1, max_length=255, examples=["Software Engineer"])
    location: str | None = Field(
        default=None, max_length=255, examples=["Mountain View, CA"]
    )
    url: str | None = Field(default=None, max_length=2048, examples=["https://careers.google.com/jobs/123"])
    date_posted: date | None = Field(default=None, examples=["2026-09-01"])
    source: str | None = Field(
        default=None, max_length=100, examples=["LinkedIn"]
    )


# ── Create schema (incoming payload) ────────────────────────────────────
class ApplicationCreate(ApplicationBase):
    """Schema for creating a new application — inherits all base fields."""

    pass


# ── Full DB record ──────────────────────────────────────────────────────
class ApplicationInDB(ApplicationBase):
    """Schema that mirrors a row in the ``applications`` table."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: ApplicationStatus = ApplicationStatus.UNAPPLIED
    created_at: datetime
    updated_at: datetime
    notes: str | None = None
    email_thread_id: str | None = None


# ── Partial update ──────────────────────────────────────────────────────
class ApplicationUpdate(BaseModel):
    """Schema for PATCH updates — every field is optional."""

    status: ApplicationStatus | None = None
    notes: str | None = None


# ── Response schema ─────────────────────────────────────────────────────
class ApplicationResponse(ApplicationInDB):
    """Public API response schema (currently identical to the DB record)."""

    pass
