"""
OpenAI-powered email parser for job-application events.

Sends the email content to GPT and receives a validated
``ApplicationEvent`` via structured outputs, then applies
business-logic filtering (confidence threshold, GENERAL discard).
"""

from __future__ import annotations

import logging
from functools import lru_cache

from openai import AsyncOpenAI

from src.core.config import get_settings
from src.email_pipeline.schemas import ApplicationEvent, EmailEventType

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_client() -> AsyncOpenAI:
    """Return a cached client pointed at the configured LLM endpoint.

    Cached because constructing a client per email would open a fresh
    connection pool for every inbound webhook.
    """
    settings = get_settings()
    return AsyncOpenAI(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
    )


_SYSTEM_PROMPT = """\
You are an expert assistant that analyses emails and determines whether they \
relate to a job application.  For each email you MUST return a JSON object \
matching the provided schema.

Guidelines:
1. Identify the event type:
   - APPLICATION_CONFIRMATION — the company acknowledges receipt of an application.
   - REJECTION — the applicant has been turned down.
   - INTERVIEW_INVITATION — the applicant is invited to an interview.
   - OA_INVITATION — the applicant is asked to complete an online assessment.
   - OFFER — the applicant receives a job offer.
   - GENERAL — the email is unrelated to a specific job application event.
2. Extract the company name verbatim from the email.
3. Extract the role / job title when mentioned.
4. Extract any actionable date (interview date, assessment deadline, etc.).
5. Put any other useful details (link, location, interviewer) in the \
   ``details`` field.
6. Set ``confidence`` between 0 and 1 reflecting how certain you are.
"""


async def extract_application_event(
    email_subject: str,
    email_body: str,
    sender: str,
) -> ApplicationEvent | None:
    """
    Parse an email and return an ``ApplicationEvent`` if it describes a
    job-application event with sufficient confidence.

    Returns ``None`` when:
    - the model classifies the email as ``GENERAL``
    - the model's confidence is below 0.5
    - an API or parsing error occurs

    Parameters
    ----------
    email_subject:
        The ``Subject`` header of the email.
    email_body:
        Plain-text body of the email.
    sender:
        The ``From`` header (name + address).

    Returns
    -------
    ApplicationEvent | None
    """
    client = _get_client()

    user_message = (
        f"From: {sender}\n"
        f"Subject: {email_subject}\n\n"
        f"{email_body}"
    )

    try:
        completion = await client.beta.chat.completions.parse(
            model=get_settings().llm_model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            response_format=ApplicationEvent,
        )
        event: ApplicationEvent | None = completion.choices[0].message.parsed

        if event is None:
            logger.warning("OpenAI returned an unparseable response.")
            return None

        # ── Business-logic gate ─────────────────────────────────────
        if event.event_type is EmailEventType.GENERAL:
            logger.debug("Discarding GENERAL event for email: %s", email_subject)
            return None

        if event.confidence < 0.5:
            logger.debug(
                "Discarding low-confidence (%.2f) event for email: %s",
                event.confidence,
                email_subject,
            )
            return None

        logger.info(
            "Extracted %s event — company=%s, role=%s (confidence=%.2f)",
            event.event_type.value,
            event.company,
            event.role,
            event.confidence,
        )
        return event

    except Exception:
        logger.exception("Failed to extract application event from email: %s", email_subject)
        return None
