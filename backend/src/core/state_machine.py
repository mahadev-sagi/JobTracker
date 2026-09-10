"""
Application-status state machine.

Defines the canonical set of statuses an application can be in and the
valid transitions between them.  Use ``transition()`` to move between
states safely – it raises ``ValueError`` for illegal moves.
"""

from __future__ import annotations

from enum import StrEnum


class ApplicationStatus(StrEnum):
    """All possible statuses for a job application."""

    UNAPPLIED = "UNAPPLIED"
    APPLIED = "APPLIED"
    OA_RECEIVED = "OA_RECEIVED"
    INTERVIEW_SCHEDULED = "INTERVIEW_SCHEDULED"
    INTERVIEWED = "INTERVIEWED"
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    GHOSTED = "GHOSTED"


# ── Allowed transitions ────────────────────────────────────────────────
# Each key maps to the frozenset of statuses it may transition *to*.
VALID_TRANSITIONS: dict[ApplicationStatus, frozenset[ApplicationStatus]] = {
    ApplicationStatus.UNAPPLIED: frozenset(
        {
            ApplicationStatus.APPLIED,
            ApplicationStatus.WITHDRAWN,
        }
    ),
    ApplicationStatus.APPLIED: frozenset(
        {
            ApplicationStatus.OA_RECEIVED,
            ApplicationStatus.INTERVIEW_SCHEDULED,
            ApplicationStatus.OFFERED,
            ApplicationStatus.REJECTED,
            ApplicationStatus.WITHDRAWN,
            ApplicationStatus.GHOSTED,
        }
    ),
    ApplicationStatus.OA_RECEIVED: frozenset(
        {
            ApplicationStatus.INTERVIEW_SCHEDULED,
            ApplicationStatus.REJECTED,
            ApplicationStatus.WITHDRAWN,
            ApplicationStatus.GHOSTED,
        }
    ),
    ApplicationStatus.INTERVIEW_SCHEDULED: frozenset(
        {
            ApplicationStatus.INTERVIEWED,
            ApplicationStatus.REJECTED,
            ApplicationStatus.WITHDRAWN,
        }
    ),
    ApplicationStatus.INTERVIEWED: frozenset(
        {
            ApplicationStatus.INTERVIEW_SCHEDULED,  # additional rounds
            ApplicationStatus.OFFERED,
            ApplicationStatus.REJECTED,
            ApplicationStatus.WITHDRAWN,
            ApplicationStatus.GHOSTED,
        }
    ),
    ApplicationStatus.OFFERED: frozenset(
        {
            ApplicationStatus.ACCEPTED,
            ApplicationStatus.REJECTED,
            ApplicationStatus.WITHDRAWN,
        }
    ),
    # Terminal states – no further transitions allowed
    ApplicationStatus.ACCEPTED: frozenset(),
    ApplicationStatus.REJECTED: frozenset(),
    ApplicationStatus.WITHDRAWN: frozenset(),
    ApplicationStatus.GHOSTED: frozenset(),
}


def can_transition(
    from_status: ApplicationStatus,
    to_status: ApplicationStatus,
) -> bool:
    """Return ``True`` if *from_status* → *to_status* is a legal move."""
    allowed = VALID_TRANSITIONS.get(from_status, frozenset())
    return to_status in allowed


def transition(
    from_status: ApplicationStatus,
    to_status: ApplicationStatus,
) -> ApplicationStatus:
    """Validate and execute a status transition.

    Returns
    -------
    ApplicationStatus
        The new status (*to_status*) on success.

    Raises
    ------
    ValueError
        If the transition is not allowed.
    """
    if not can_transition(from_status, to_status):
        allowed = VALID_TRANSITIONS.get(from_status, frozenset())
        allowed_names = sorted(s.value for s in allowed) if allowed else ["(none)"]
        raise ValueError(
            f"Invalid transition: {from_status.value} → {to_status.value}. "
            f"Allowed targets from {from_status.value}: {', '.join(allowed_names)}"
        )
    return to_status
