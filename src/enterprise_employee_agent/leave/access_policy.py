"""Authorization policy and role-specific projections (Issue #9).

# ANCHOR: The only place that decides what a resolved DemoIdentity may view, command, replay,
# or read the audit history of, and the only place that turns an internal LeaveRequest into the
# employee/manager/HR projection. Has no I/O, so #10 (storage) and #11 (confirmation) can call it
# inside their own transactions. Fails closed: an out-of-scope request looks not_found (D3), and
# a role that never has a command is forbidden before any lookup.
"""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import TypeAdapter, ValidationError

from enterprise_employee_agent.leave.contracts import (
    COMMAND_SPECS,
    ActorRole,
    CommandName,
    DemoAccessManifest,
    DemoIdentity,
    EmployeeLeaveProjection,
    HrLeaveProjection,
    Identifier,
    LeaveRequest,
    ManagerLeaveProjection,
    WorkflowError,
    WorkflowErrorCode,
)

_IDENTIFIER_ADAPTER = TypeAdapter(Identifier)

type LeaveProjection = EmployeeLeaveProjection | ManagerLeaveProjection | HrLeaveProjection


def resolve_identity(manifest: DemoAccessManifest, actor_id: str) -> DemoIdentity:
    """The only way to obtain an actor: server-selected, never client- or model-supplied."""
    try:
        validated_id = _IDENTIFIER_ADAPTER.validate_python(actor_id)
    except ValidationError as error:
        raise WorkflowError(WorkflowErrorCode.UNAUTHORIZED) from error
    identity = _find_identity(manifest, validated_id)
    if identity is None:
        raise WorkflowError(WorkflowErrorCode.UNAUTHORIZED)
    return identity


def _find_identity(manifest: DemoAccessManifest, identity_id: str) -> DemoIdentity | None:
    return next(
        (candidate for candidate in manifest.identities if candidate.identity_id == identity_id),
        None,
    )


def can_view(manifest: DemoAccessManifest, actor: DemoIdentity, request: LeaveRequest) -> bool:
    """Whether ``actor`` may view ``request`` at all, independent of any specific command."""
    if actor.role is ActorRole.EMPLOYEE:
        return actor.identity_id == request.employee_id
    if actor.role is ActorRole.MANAGER:
        owner = _find_identity(manifest, request.employee_id)
        return owner is not None and owner.reports_to == actor.identity_id
    if actor.role is ActorRole.HR:
        return True
    return False


def visible_requests(
    manifest: DemoAccessManifest, actor: DemoIdentity, requests: Iterable[LeaveRequest]
) -> tuple[LeaveRequest, ...]:
    """Filter a list of requests to the ones ``actor`` may view, for list endpoints."""
    return tuple(request for request in requests if can_view(manifest, actor, request))


def authorize_command(
    manifest: DemoAccessManifest,
    actor: DemoIdentity,
    command: CommandName,
    request: LeaveRequest | None,
) -> None:
    """Authorize a command. Forbidden if the role never has it; not_found if out of scope (D3)."""
    if actor.role not in COMMAND_SPECS[command].allowed_roles:
        raise WorkflowError(WorkflowErrorCode.FORBIDDEN)
    if command is CommandName.CREATE_DRAFT:
        return
    if request is None or not can_view(manifest, actor, request):
        raise WorkflowError(WorkflowErrorCode.NOT_FOUND)


def authorize_replay(
    manifest: DemoAccessManifest, actor: DemoIdentity, stored_request: LeaveRequest
) -> None:
    """Deny replaying a stored idempotent result to anyone who could not view it live."""
    if not can_view(manifest, actor, stored_request):
        raise WorkflowError(WorkflowErrorCode.NOT_FOUND)


def authorize_audit_history(
    manifest: DemoAccessManifest, actor: DemoIdentity, request: LeaveRequest
) -> None:
    """``audit_history`` is HR-only (contract v1); scope still applies within that role."""
    if actor.role is not ActorRole.HR:
        raise WorkflowError(WorkflowErrorCode.FORBIDDEN)
    if not can_view(manifest, actor, request):
        raise WorkflowError(WorkflowErrorCode.NOT_FOUND)


def project_for(
    manifest: DemoAccessManifest, actor: DemoIdentity, request: LeaveRequest
) -> LeaveProjection:
    """Build the typed projection for ``actor``'s role after authorization."""
    if not can_view(manifest, actor, request):
        raise WorkflowError(WorkflowErrorCode.NOT_FOUND)
    payload = request.payload
    if actor.role is ActorRole.EMPLOYEE:
        return EmployeeLeaveProjection(
            request_id=request.request_id,
            employee_id=request.employee_id,
            status=request.status,
            version=request.version,
            start_date=payload.start_date,
            end_date=payload.end_date,
            request_type=payload.request_type,
            employee_comment=payload.employee_comment,
            clarification_question=request.clarification_question,
            updated_at=request.updated_at,
            action_history=tuple(
                event for event in request.audit_history if event.actor_id == request.employee_id
            ),
        )
    if actor.role is ActorRole.MANAGER:
        return ManagerLeaveProjection(
            request_id=request.request_id,
            employee_id=request.employee_id,
            status=request.status,
            start_date=payload.start_date,
            end_date=payload.end_date,
            request_type=payload.request_type,
        )
    return HrLeaveProjection(
        request_id=request.request_id,
        employee_id=request.employee_id,
        status=request.status,
        version=request.version,
        start_date=payload.start_date,
        end_date=payload.end_date,
        request_type=payload.request_type,
        employee_comment=payload.employee_comment,
        clarification_question=request.clarification_question,
        updated_at=request.updated_at,
        audit_history=request.audit_history,
    )
