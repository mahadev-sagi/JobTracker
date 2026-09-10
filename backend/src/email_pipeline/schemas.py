"""
Pydantic models for OpenAI Structured Outputs — email event extraction.

These schemas are passed directly as ``response_format`` to the OpenAI chat
completions API so the model returns validated, typed JSON every time.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class EmailEventType(str, Enum):
    """Categories of job-application-related email events."""

    APPLICATION_CONFIRMATION = "APPLICATION_CONFIRMATION"
    REJECTION = "REJECTION"
    INTERVIEW_INVITATION = "INTERVIEW_INVITATION"
    OA_INVITATION = "OA_INVITATION"
    OFFER = "OFFER"
    GENERAL = "GENERAL"


class ApplicationEvent(BaseModel):
    """
    Structured representation of a job-application event extracted from
    an email.

    The ``confidence`` score (0 → 1) reflects how certain the model is
    that it correctly identified the event.  Downstream code typically
    discards events with ``confidence < 0.5`` or those typed as
    ``GENERAL``.
    """

    event_type: EmailEventType = Field(
        ...,
        description=(
            "The category of job-application event detected in the email. "
            "Use GENERAL when the email is not related to a job application."
        ),
    )
    company: str = Field(
        ...,
        description="The company name associated with this application event.",
    )
    role: str | None = Field(
        default=None,
        description="The job title / role mentioned in the email, if identifiable.",
    )
    date: str | None = Field(
        default=None,
        description=(
            "A relevant date extracted from the email body (e.g. interview "
            "date, deadline).  ISO-8601 preferred, but free-form is acceptable."
        ),
    )
    details: str | None = Field(
        default=None,
        description="Any extra useful information (location, interviewer name, link, etc.).",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description=(
            "Model's self-assessed confidence (0–1) that it correctly "
            "identified the event type and extracted the fields."
        ),
    )

    # Pydantic v2 model config — ensures the JSON schema generated for
    # OpenAI structured outputs is clean and complete.
    model_config = {
        "json_schema_extra": {
            "additionalProperties": False,
        },
    }
