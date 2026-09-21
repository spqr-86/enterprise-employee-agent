"""Unit tests for deterministic leave command application."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from enterprise_employee_agent.leave.contracts import (
    CommandName,
    LeaveRequest,
    LeaveRequestPayload,
    LeaveStatus,
    RequestType,
    WorkflowError,
    WorkflowErrorCode,
)
from enterprise_employee_agent.leave.state_machine import transition_target


def _request(status: LeaveStatus) -> LeaveRequest:
    return LeaveRequest(
        request_id="leave-alice-001",
        employee_id="employee-alice",
        status=status,
        version=1,
        payload=LeaveRequestPayload(
            start_date=date(2026, 10, 1),
            end_date=date(2026, 10, 5),
            request_type=RequestType.CONTINUOUS,
        ),
        clarification_question=None,
        updated_at=datetime(2026, 9, 21, 10, 0, tzinfo=UTC),
        audit_history=(),
    )


@pytest.mark.parametrize(
    ("status", "command", "target"),
    [
        (LeaveStatus.DRAFT, CommandName.UPDATE_DRAFT, LeaveStatus.DRAFT),
        (LeaveStatus.DRAFT, CommandName.CANCEL_DRAFT, LeaveStatus.CANCELLED),
        (LeaveStatus.DRAFT, CommandName.CONFIRM_SUBMIT, LeaveStatus.SUBMITTED),
        (LeaveStatus.SUBMITTED, CommandName.START_PROCESSING, LeaveStatus.PROCESSING),
        (
            LeaveStatus.SUBMITTED,
            CommandName.REQUEST_CLARIFICATION,
            LeaveStatus.NEEDS_CLARIFICATION,
        ),
        (
            LeaveStatus.NEEDS_CLARIFICATION,
            CommandName.PROVIDE_CLARIFICATION,
            LeaveStatus.NEEDS_CLARIFICATION,
        ),
        (
            LeaveStatus.NEEDS_CLARIFICATION,
            CommandName.CONFIRM_SUBMIT,
            LeaveStatus.SUBMITTED,
        ),
    ],
)
def test_transition_target_allows_only_v01_behavior(status, command, target) -> None:
    assert transition_target(_request(status), command) is target


@pytest.mark.parametrize("status", list(LeaveStatus))
def test_create_is_not_a_transition_on_an_existing_request(status) -> None:
    with pytest.raises(WorkflowError) as excinfo:
        transition_target(_request(status), CommandName.CREATE_DRAFT)
    assert excinfo.value.code is WorkflowErrorCode.INVALID_TRANSITION


def test_invalid_transition_returns_safe_domain_error() -> None:
    with pytest.raises(WorkflowError) as excinfo:
        transition_target(_request(LeaveStatus.PROCESSING), CommandName.CANCEL_DRAFT)
    assert excinfo.value.code is WorkflowErrorCode.INVALID_TRANSITION


def test_every_undeclared_status_command_pair_is_forbidden() -> None:
    allowed = {
        (LeaveStatus.DRAFT, CommandName.UPDATE_DRAFT),
        (LeaveStatus.DRAFT, CommandName.CANCEL_DRAFT),
        (LeaveStatus.DRAFT, CommandName.CONFIRM_SUBMIT),
        (LeaveStatus.SUBMITTED, CommandName.START_PROCESSING),
        (LeaveStatus.SUBMITTED, CommandName.REQUEST_CLARIFICATION),
        (LeaveStatus.NEEDS_CLARIFICATION, CommandName.PROVIDE_CLARIFICATION),
        (LeaveStatus.NEEDS_CLARIFICATION, CommandName.CONFIRM_SUBMIT),
    }
    for status in LeaveStatus:
        for command in CommandName:
            if (status, command) in allowed:
                continue
            with pytest.raises(WorkflowError) as excinfo:
                transition_target(_request(status), command)
            assert excinfo.value.code is WorkflowErrorCode.INVALID_TRANSITION
