"""
Tests for the application lifecycle state machine.

Covers valid transitions, invalid transitions (ValueError), the
``can_transition`` predicate, and enum completeness.
"""

from __future__ import annotations

import pytest

from src.core.state_machine import ApplicationStatus, VALID_TRANSITIONS, can_transition, transition


# ═══════════════════════════════════════════════════════════════════
#  Enum completeness
# ═══════════════════════════════════════════════════════════════════


class TestApplicationStatusEnum:
    """Ensure the enum and transition map stay in sync."""

    EXPECTED_STATES = {
        "UNAPPLIED",
        "APPLIED",
        "OA_RECEIVED",
        "INTERVIEW_SCHEDULED",
        "INTERVIEWED",
        "OFFERED",
        "ACCEPTED",
        "REJECTED",
        "WITHDRAWN",
        "GHOSTED",
    }

    def test_all_states_present(self):
        """Every expected state is a member of the enum."""
        actual = {s.value for s in ApplicationStatus}
        assert actual == self.EXPECTED_STATES

    def test_transitions_cover_all_states(self):
        """The VALID_TRANSITIONS map has an entry for every status."""
        for status in ApplicationStatus:
            assert status in VALID_TRANSITIONS, f"{status} missing from VALID_TRANSITIONS"


# ═══════════════════════════════════════════════════════════════════
#  can_transition
# ═══════════════════════════════════════════════════════════════════


class TestCanTransition:
    """Tests for the ``can_transition`` predicate."""

    @pytest.mark.parametrize(
        ("src", "dst"),
        [
            (ApplicationStatus.UNAPPLIED, ApplicationStatus.APPLIED),
            (ApplicationStatus.APPLIED, ApplicationStatus.OA_RECEIVED),
            (ApplicationStatus.APPLIED, ApplicationStatus.INTERVIEW_SCHEDULED),
            (ApplicationStatus.APPLIED, ApplicationStatus.OFFERED),
            (ApplicationStatus.APPLIED, ApplicationStatus.REJECTED),
            (ApplicationStatus.APPLIED, ApplicationStatus.WITHDRAWN),
            (ApplicationStatus.OA_RECEIVED, ApplicationStatus.INTERVIEW_SCHEDULED),
            (ApplicationStatus.OA_RECEIVED, ApplicationStatus.REJECTED),
            (ApplicationStatus.INTERVIEW_SCHEDULED, ApplicationStatus.INTERVIEWED),
            (ApplicationStatus.INTERVIEW_SCHEDULED, ApplicationStatus.REJECTED),
            (ApplicationStatus.INTERVIEWED, ApplicationStatus.OFFERED),
            (ApplicationStatus.INTERVIEWED, ApplicationStatus.REJECTED),
            (ApplicationStatus.OFFERED, ApplicationStatus.ACCEPTED),
            (ApplicationStatus.OFFERED, ApplicationStatus.REJECTED),
            (ApplicationStatus.OFFERED, ApplicationStatus.WITHDRAWN),
        ],
    )
    def test_valid_transition_returns_true(self, src: ApplicationStatus, dst: ApplicationStatus):
        assert can_transition(src, dst) is True

    @pytest.mark.parametrize(
        ("src", "dst"),
        [
            # Terminal states have no outgoing edges.
            (ApplicationStatus.REJECTED, ApplicationStatus.APPLIED),
            (ApplicationStatus.WITHDRAWN, ApplicationStatus.APPLIED),
            (ApplicationStatus.ACCEPTED, ApplicationStatus.REJECTED),
            # Backward / nonsensical jumps.
            (ApplicationStatus.INTERVIEW_SCHEDULED, ApplicationStatus.UNAPPLIED),
            (ApplicationStatus.OA_RECEIVED, ApplicationStatus.APPLIED),
            (ApplicationStatus.OFFERED, ApplicationStatus.OA_RECEIVED),
            # Self-loops are not allowed.
            (ApplicationStatus.APPLIED, ApplicationStatus.APPLIED),
        ],
    )
    def test_invalid_transition_returns_false(self, src: ApplicationStatus, dst: ApplicationStatus):
        assert can_transition(src, dst) is False


# ═══════════════════════════════════════════════════════════════════
#  transition()
# ═══════════════════════════════════════════════════════════════════


class TestTransition:
    """Tests for the ``transition`` function."""

    def test_valid_transition_returns_target(self):
        """A valid transition returns the target status."""
        result = transition(ApplicationStatus.UNAPPLIED, ApplicationStatus.APPLIED)
        assert result is ApplicationStatus.APPLIED

    def test_applied_to_oa_received(self):
        result = transition(ApplicationStatus.APPLIED, ApplicationStatus.OA_RECEIVED)
        assert result is ApplicationStatus.OA_RECEIVED

    def test_interview_to_interviewed(self):
        result = transition(
            ApplicationStatus.INTERVIEW_SCHEDULED,
            ApplicationStatus.INTERVIEWED,
        )
        assert result is ApplicationStatus.INTERVIEWED

    def test_interviewed_to_offered(self):
        result = transition(
            ApplicationStatus.INTERVIEWED,
            ApplicationStatus.OFFERED,
        )
        assert result is ApplicationStatus.OFFERED

    def test_offer_to_accepted(self):
        result = transition(
            ApplicationStatus.OFFERED,
            ApplicationStatus.ACCEPTED,
        )
        assert result is ApplicationStatus.ACCEPTED

    def test_invalid_transition_raises_value_error(self):
        """An illegal transition must raise ``ValueError``."""
        with pytest.raises(ValueError, match="Cannot transition"):
            transition(ApplicationStatus.REJECTED, ApplicationStatus.APPLIED)

    def test_terminal_rejected_raises(self):
        with pytest.raises(ValueError):
            transition(ApplicationStatus.REJECTED, ApplicationStatus.INTERVIEW_SCHEDULED)

    def test_terminal_withdrawn_raises(self):
        with pytest.raises(ValueError):
            transition(ApplicationStatus.WITHDRAWN, ApplicationStatus.APPLIED)

    def test_terminal_accepted_raises(self):
        with pytest.raises(ValueError):
            transition(ApplicationStatus.ACCEPTED, ApplicationStatus.REJECTED)

    def test_backward_transition_raises(self):
        with pytest.raises(ValueError):
            transition(ApplicationStatus.INTERVIEW_SCHEDULED, ApplicationStatus.UNAPPLIED)

    def test_self_loop_raises(self):
        """Self-transitions are not allowed."""
        with pytest.raises(ValueError):
            transition(ApplicationStatus.APPLIED, ApplicationStatus.APPLIED)


# ═══════════════════════════════════════════════════════════════════
#  Full lifecycle walk
# ═══════════════════════════════════════════════════════════════════


class TestFullLifecycle:
    """Walk the happy-path lifecycle from UNAPPLIED to ACCEPTED."""

    def test_happy_path(self):
        state = ApplicationStatus.UNAPPLIED
        state = transition(state, ApplicationStatus.APPLIED)
        state = transition(state, ApplicationStatus.OA_RECEIVED)
        state = transition(state, ApplicationStatus.INTERVIEW_SCHEDULED)
        state = transition(state, ApplicationStatus.INTERVIEWED)
        state = transition(state, ApplicationStatus.OFFERED)
        state = transition(state, ApplicationStatus.ACCEPTED)
        assert state is ApplicationStatus.ACCEPTED

    def test_rejection_shortcut(self):
        state = ApplicationStatus.UNAPPLIED
        state = transition(state, ApplicationStatus.APPLIED)
        state = transition(state, ApplicationStatus.REJECTED)
        assert state is ApplicationStatus.REJECTED
