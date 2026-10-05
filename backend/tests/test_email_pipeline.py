"""
Tests for the mapping from classified email events to application statuses.

Matching, transitions and sync run against a real database in
test_processing.py.
"""

from __future__ import annotations

import pytest
from src.core.state_machine import ApplicationStatus
from src.email_pipeline.schemas import (
    EVENT_TYPE_TO_STATUS,
    EmailEventType,
    status_for_event,
)

# ---------------------------------------------------------------------------
# Event type -> application status mapping
# ---------------------------------------------------------------------------


class TestEventStatusMapping:
    """The bridge that was missing entirely before this pipeline was wired."""

    def test_every_actionable_event_maps_to_a_status(self):
        actionable = set(EmailEventType) - {EmailEventType.GENERAL}
        assert actionable == set(EVENT_TYPE_TO_STATUS)

    def test_general_never_maps_to_a_status(self):
        assert status_for_event(EmailEventType.GENERAL) is None

    @pytest.mark.parametrize(
        ("event_type", "expected"),
        [
            (EmailEventType.APPLICATION_CONFIRMATION, ApplicationStatus.APPLIED),
            (EmailEventType.REJECTION, ApplicationStatus.REJECTED),
            (
                EmailEventType.INTERVIEW_INVITATION,
                ApplicationStatus.INTERVIEW_SCHEDULED,
            ),
            (EmailEventType.OA_INVITATION, ApplicationStatus.OA_RECEIVED),
            (EmailEventType.OFFER, ApplicationStatus.OFFERED),
        ],
    )
    def test_mapping(self, event_type, expected):
        assert status_for_event(event_type) is expected

    def test_mapped_statuses_are_real_enum_members(self):
        # Guards against the BOOKMARKED-style typo that broke POST /applications.
        for stat in EVENT_TYPE_TO_STATUS.values():
            assert ApplicationStatus(stat.value) is stat
