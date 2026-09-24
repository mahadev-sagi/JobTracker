"""
Tests for the OpenAI-powered email extractor.

All tests mock the OpenAI client so no real API calls are made.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.email_pipeline.extractor import extract_application_event
from src.email_pipeline.schemas import ApplicationEvent, EmailEventType

# ── Helpers ──────────────────────────────────────────────────────────


def _mock_completion(event: ApplicationEvent) -> MagicMock:
    """Build a mock completion object whose ``.choices[0].message.parsed`` is *event*."""
    choice = MagicMock()
    choice.message.parsed = event
    completion = MagicMock()
    completion.choices = [choice]
    return completion


def _patch_openai(event: ApplicationEvent):
    """Return a context-manager that patches ``AsyncOpenAI`` to return *event*."""
    mock_client = AsyncMock()
    mock_client.beta.chat.completions.parse = AsyncMock(
        return_value=_mock_completion(event)
    )
    return patch(
        "src.email_pipeline.extractor.AsyncOpenAI",
        return_value=mock_client,
    )


# ── Tests ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_extract_confirmation_email():
    """A clear application-confirmation email should return the correct event."""
    event = ApplicationEvent(
        event_type=EmailEventType.APPLICATION_CONFIRMATION,
        company="Google",
        role="Software Engineer",
        date=None,
        details="Application received for SWE position.",
        confidence=0.95,
    )

    with _patch_openai(event):
        result = await extract_application_event(
            email_subject="Application Received — Google",
            email_body="Thank you for applying to the Software Engineer role.",
            sender="jobs@google.com",
        )

    assert result is not None
    assert result.event_type is EmailEventType.APPLICATION_CONFIRMATION
    assert result.company == "Google"
    assert result.role == "Software Engineer"
    assert result.confidence >= 0.5


@pytest.mark.asyncio
async def test_extract_rejection_email():
    """A rejection email should return a REJECTION event."""
    event = ApplicationEvent(
        event_type=EmailEventType.REJECTION,
        company="Meta",
        role="Product Manager",
        date=None,
        details="Unfortunately we will not be moving forward.",
        confidence=0.90,
    )

    with _patch_openai(event):
        result = await extract_application_event(
            email_subject="Update on your application — Meta",
            email_body="After careful consideration, we have decided not to proceed.",
            sender="recruiting@meta.com",
        )

    assert result is not None
    assert result.event_type is EmailEventType.REJECTION
    assert result.company == "Meta"


@pytest.mark.asyncio
async def test_extract_interview_invitation():
    """An interview invitation should return an INTERVIEW_INVITATION event."""
    event = ApplicationEvent(
        event_type=EmailEventType.INTERVIEW_INVITATION,
        company="Amazon",
        role="SDE Intern",
        date="2026-10-15",
        details="Please book a slot via the link.",
        confidence=0.92,
    )

    with _patch_openai(event):
        result = await extract_application_event(
            email_subject="Interview Invitation — Amazon",
            email_body="We'd like to invite you to interview for the SDE Intern role.",
            sender="university@amazon.com",
        )

    assert result is not None
    assert result.event_type is EmailEventType.INTERVIEW_INVITATION
    assert result.date == "2026-10-15"


@pytest.mark.asyncio
async def test_low_confidence_returns_none():
    """Events with confidence below 0.5 should be discarded (return None)."""
    event = ApplicationEvent(
        event_type=EmailEventType.APPLICATION_CONFIRMATION,
        company="SomeCompany",
        role=None,
        date=None,
        details=None,
        confidence=0.3,
    )

    with _patch_openai(event):
        result = await extract_application_event(
            email_subject="Random newsletter",
            email_body="Check out our latest blog post.",
            sender="news@somecompany.com",
        )

    assert result is None


@pytest.mark.asyncio
async def test_general_event_returns_none():
    """Emails classified as GENERAL should be discarded (return None)."""
    event = ApplicationEvent(
        event_type=EmailEventType.GENERAL,
        company="LinkedIn",
        role=None,
        date=None,
        details=None,
        confidence=0.85,
    )

    with _patch_openai(event):
        result = await extract_application_event(
            email_subject="Your weekly digest",
            email_body="Here are this week's top jobs.",
            sender="notifications@linkedin.com",
        )

    assert result is None


@pytest.mark.asyncio
async def test_openai_exception_returns_none():
    """When the OpenAI call raises an exception, the extractor returns None."""
    mock_client = AsyncMock()
    mock_client.beta.chat.completions.parse = AsyncMock(
        side_effect=RuntimeError("API unavailable")
    )

    with patch(
        "src.email_pipeline.extractor.AsyncOpenAI",
        return_value=mock_client,
    ):
        result = await extract_application_event(
            email_subject="Test",
            email_body="body",
            sender="x@example.com",
        )

    assert result is None
