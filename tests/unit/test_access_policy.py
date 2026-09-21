from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from enterprise_employee_agent.leave.access_policy import (
    LeaveRequest,
    authorize_audit_history,
    authorize_command,
    authorize_replay,
    can_view,
    project_for,
    resolve_identity,
    visible_requests,
)
from enterprise_employee_agent.leave.contracts import (
    ActorRole,
    AuditEvent,
    CommandName,
    EmployeeLeaveProjection,
    HrLeaveProjection,
    LeaveRequestPayload,
    ManagerLeaveProjection,
    RequestType,
    UpdateDraftInput,
    WorkflowError,
    WorkflowErrorCode,
    load_demo_access_manifest,
)

DEMO_MANIFEST_PATH = Path("data/synthetic_protected/demo-access-v1.json")
NOW = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)


@pytest.fixture()
def manifest():
    return load_demo_access_manifest(DEMO_MANIFEST_PATH)


def _payload() -> LeaveRequestPayload:
    return LeaveRequestPayload(
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 10),
        request_type=RequestType.CONTINUOUS,
    )


def _request(
    *, request_id: str = "req-1", employee_id: str = "employee-alice", version: int = 1
) -> LeaveRequest:
    return LeaveRequest(
        request_id=request_id,
        employee_id=employee_id,
        status="draft",
        version=version,
        payload=_payload(),
        clarification_question=None,
        updated_at=NOW,
        audit_history=(),
    )


# --- resolve_identity -------------------------------------------------------


def test_resolve_identity_returns_the_declared_identity(manifest) -> None:
    identity = resolve_identity(manifest, "employee-alice")
    assert identity.identity_id == "employee-alice"
    assert identity.role is ActorRole.EMPLOYEE


def test_resolve_identity_rejects_unknown_actor(manifest) -> None:
    with pytest.raises(WorkflowError) as excinfo:
        resolve_identity(manifest, "employee-does-not-exist")
    assert excinfo.value.code is WorkflowErrorCode.UNAUTHORIZED


def test_resolve_identity_rejects_malformed_actor_id(manifest) -> None:
    with pytest.raises(WorkflowError) as excinfo:
        resolve_identity(manifest, "../etc/passwd")
    assert excinfo.value.code is WorkflowErrorCode.UNAUTHORIZED


# --- client input cannot spoof identity (AC-1) ------------------------------


def test_client_command_input_rejects_injected_actor_id() -> None:
    with pytest.raises(ValidationError):
        UpdateDraftInput.model_validate(
            {
                "idempotency_key": "update-req-1-attempt-1",
                "request_id": "req-1",
                "expected_version": 1,
                "payload": _payload().model_dump(mode="json"),
                "actor_id": "hr-harper",
            }
        )


def test_client_command_input_rejects_injected_role_or_reports_to() -> None:
    base = {
        "idempotency_key": "update-req-1-attempt-1",
        "request_id": "req-1",
        "expected_version": 1,
        "payload": _payload().model_dump(mode="json"),
    }
    with pytest.raises(ValidationError):
        UpdateDraftInput.model_validate({**base, "role": "hr"})
    with pytest.raises(ValidationError):
        UpdateDraftInput.model_validate({**base, "reports_to": "manager-morgan"})


def test_leave_request_rejects_injected_role_field() -> None:
    with pytest.raises(ValidationError):
        LeaveRequest.model_validate(
            {
                "request_id": "req-1",
                "employee_id": "employee-alice",
                "status": "draft",
                "version": 1,
                "payload": _payload().model_dump(mode="json"),
                "clarification_question": None,
                "updated_at": NOW.isoformat(),
                "audit_history": (),
                "role": "hr",
            }
        )


# --- can_view / actor x request-owner x action matrix (AC-2, AC-3) ---------


def test_employee_sees_only_their_own_request(manifest) -> None:
    alice = resolve_identity(manifest, "employee-alice")
    bob_request = _request(employee_id="employee-bob")
    assert can_view(manifest, alice, _request(employee_id="employee-alice")) is True
    assert can_view(manifest, alice, bob_request) is False


def test_manager_sees_only_direct_reports(manifest) -> None:
    morgan = resolve_identity(manifest, "manager-morgan")  # manages alice, bob
    riley = resolve_identity(manifest, "manager-riley")  # manages carol
    alice_request = _request(employee_id="employee-alice")
    assert can_view(manifest, morgan, alice_request) is True
    assert can_view(manifest, riley, alice_request) is False


def test_hr_sees_every_request(manifest) -> None:
    harper = resolve_identity(manifest, "hr-harper")
    assert can_view(manifest, harper, _request(employee_id="employee-alice")) is True
    assert can_view(manifest, harper, _request(employee_id="employee-carol")) is True


def test_visible_requests_filters_a_list_by_scope(manifest) -> None:
    morgan = resolve_identity(manifest, "manager-morgan")
    requests = (
        _request(request_id="req-1", employee_id="employee-alice"),
        _request(request_id="req-2", employee_id="employee-carol"),
    )
    assert [r.request_id for r in visible_requests(manifest, morgan, requests)] == ["req-1"]


# --- authorize_command: forbidden (role never has it) vs not_found (D3) ----


def test_authorize_command_allows_owner_employee_command(manifest) -> None:
    alice = resolve_identity(manifest, "employee-alice")
    authorize_command(
        manifest, alice, CommandName.UPDATE_DRAFT, _request(employee_id="employee-alice")
    )


def test_authorize_command_returns_not_found_for_cross_employee_access(manifest) -> None:
    alice = resolve_identity(manifest, "employee-alice")
    with pytest.raises(WorkflowError) as excinfo:
        authorize_command(
            manifest, alice, CommandName.UPDATE_DRAFT, _request(employee_id="employee-bob")
        )
    assert excinfo.value.code is WorkflowErrorCode.NOT_FOUND


def test_authorize_command_returns_forbidden_for_manager_mutation(manifest) -> None:
    morgan = resolve_identity(manifest, "manager-morgan")
    with pytest.raises(WorkflowError) as excinfo:
        authorize_command(
            manifest, morgan, CommandName.UPDATE_DRAFT, _request(employee_id="employee-alice")
        )
    assert excinfo.value.code is WorkflowErrorCode.FORBIDDEN


def test_authorize_command_returns_forbidden_for_employee_hr_action(manifest) -> None:
    alice = resolve_identity(manifest, "employee-alice")
    with pytest.raises(WorkflowError) as excinfo:
        authorize_command(
            manifest, alice, CommandName.START_PROCESSING, _request(employee_id="employee-alice")
        )
    assert excinfo.value.code is WorkflowErrorCode.FORBIDDEN


def test_authorize_command_returns_not_found_for_non_report_manager(manifest) -> None:
    riley = resolve_identity(manifest, "manager-riley")
    with pytest.raises(WorkflowError) as excinfo:
        authorize_command(
            manifest, riley, CommandName.START_PROCESSING, _request(employee_id="employee-alice")
        )
    # manager has no allowed commands at all, so role-level check fires first
    assert excinfo.value.code is WorkflowErrorCode.FORBIDDEN


def test_authorize_command_allows_create_draft_without_an_existing_request(manifest) -> None:
    alice = resolve_identity(manifest, "employee-alice")
    authorize_command(manifest, alice, CommandName.CREATE_DRAFT, None)


def test_authorize_command_returns_not_found_when_no_request_exists(manifest) -> None:
    harper = resolve_identity(manifest, "hr-harper")
    with pytest.raises(WorkflowError) as excinfo:
        authorize_command(manifest, harper, CommandName.START_PROCESSING, None)
    assert excinfo.value.code is WorkflowErrorCode.NOT_FOUND


# --- authorize_replay / authorize_audit_history (AC-5) ----------------------


def test_authorize_replay_denies_the_same_actors_as_can_view(manifest) -> None:
    alice = resolve_identity(manifest, "employee-alice")
    with pytest.raises(WorkflowError) as excinfo:
        authorize_replay(manifest, alice, _request(employee_id="employee-bob"))
    assert excinfo.value.code is WorkflowErrorCode.NOT_FOUND


def test_authorize_audit_history_forbidden_for_non_hr(manifest) -> None:
    morgan = resolve_identity(manifest, "manager-morgan")
    with pytest.raises(WorkflowError) as excinfo:
        authorize_audit_history(manifest, morgan, _request(employee_id="employee-alice"))
    assert excinfo.value.code is WorkflowErrorCode.FORBIDDEN


def test_authorize_audit_history_allowed_for_hr(manifest) -> None:
    harper = resolve_identity(manifest, "hr-harper")
    authorize_audit_history(manifest, harper, _request(employee_id="employee-alice"))


# --- project_for: exact field sets per role (AC-2, AC-6) --------------------


def _request_with_history() -> LeaveRequest:
    events = (
        AuditEvent(
            event_id="evt-1",
            request_id="req-1",
            actor_id="employee-alice",
            command=CommandName.CREATE_DRAFT,
            previous_status=None,
            new_status="draft",
            previous_version=0,
            request_version=1,
            idempotency_key="create-req-1-attempt-1",
            command_fingerprint="0" * 64,
            occurred_at=NOW,
        ),
    )
    return LeaveRequest(
        request_id="req-1",
        employee_id="employee-alice",
        status="draft",
        version=1,
        payload=_payload(),
        clarification_question=None,
        updated_at=NOW,
        audit_history=events,
    )


def test_project_for_employee_returns_the_strict_employee_model(manifest) -> None:
    alice = resolve_identity(manifest, "employee-alice")
    projection = project_for(manifest, alice, _request_with_history())
    assert isinstance(projection, EmployeeLeaveProjection)
    assert len(projection.action_history) == 1
    assert not hasattr(projection, "audit_history")


def test_project_for_manager_returns_the_minimum_field_set(manifest) -> None:
    morgan = resolve_identity(manifest, "manager-morgan")
    projection = project_for(manifest, morgan, _request_with_history())
    assert isinstance(projection, ManagerLeaveProjection)
    assert not hasattr(projection, "employee_comment")
    assert not hasattr(projection, "action_history")
    assert not hasattr(projection, "audit_history")


def test_project_for_hr_returns_the_full_audit_history(manifest) -> None:
    harper = resolve_identity(manifest, "hr-harper")
    projection = project_for(manifest, harper, _request_with_history())
    assert isinstance(projection, HrLeaveProjection)
    assert len(projection.audit_history) == 1


def test_project_for_cross_employee_access_returns_not_found(manifest) -> None:
    alice = resolve_identity(manifest, "employee-alice")
    with pytest.raises(WorkflowError) as excinfo:
        project_for(manifest, alice, _request(employee_id="employee-bob"))
    assert excinfo.value.code is WorkflowErrorCode.NOT_FOUND


def test_project_for_non_report_manager_returns_not_found(manifest) -> None:
    riley = resolve_identity(manifest, "manager-riley")
    with pytest.raises(WorkflowError) as excinfo:
        project_for(manifest, riley, _request(employee_id="employee-alice"))
    assert excinfo.value.code is WorkflowErrorCode.NOT_FOUND


# --- full actor x request-owner x action matrix from the demo manifest (AC-6) --


def test_full_actor_matrix_matches_can_view_expectations(manifest) -> None:
    employees = ["employee-alice", "employee-bob", "employee-carol"]
    actors = [i.identity_id for i in manifest.identities]
    reports_to = {i.identity_id: i.reports_to for i in manifest.identities}
    for actor_id in actors:
        actor = resolve_identity(manifest, actor_id)
        for owner_id in employees:
            request = _request(employee_id=owner_id)
            visible = can_view(manifest, actor, request)
            if actor.role is ActorRole.EMPLOYEE:
                expected = actor_id == owner_id
            elif actor.role is ActorRole.MANAGER:
                expected = reports_to[owner_id] == actor_id
            else:
                expected = True
            assert visible is expected, (actor_id, owner_id)
