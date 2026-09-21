"""Deterministic v0.1 leave state transitions."""

# ANCHOR: Maps a current LeaveRequest and typed command name to the only allowed v0.1 target
# status. It performs no authorization, confirmation, persistence, or provider work.

from enterprise_employee_agent.leave.contracts import (
    TRANSITIONS,
    CommandName,
    LeaveRequest,
    LeaveStatus,
    WorkflowError,
    WorkflowErrorCode,
)

_SAME_STATUS_COMMANDS: dict[tuple[LeaveStatus, CommandName], LeaveStatus] = {
    (LeaveStatus.DRAFT, CommandName.UPDATE_DRAFT): LeaveStatus.DRAFT,
    (
        LeaveStatus.NEEDS_CLARIFICATION,
        CommandName.PROVIDE_CLARIFICATION,
    ): LeaveStatus.NEEDS_CLARIFICATION,
}

_TRANSITION_TARGETS = {
    (transition.source, transition.command): transition.target for transition in TRANSITIONS
}


def transition_target(request: LeaveRequest, command: CommandName) -> LeaveStatus:
    """Return the declared next status or fail with a safe domain error."""

    target = _SAME_STATUS_COMMANDS.get((request.status, command))
    if target is None:
        target = _TRANSITION_TARGETS.get((request.status, command))
    if target is None:
        raise WorkflowError(WorkflowErrorCode.INVALID_TRANSITION)
    return target
