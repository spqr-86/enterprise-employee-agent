"""Contract tests for the v0.1 leave workflow and demo fixtures."""

from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

import enterprise_employee_agent.leave.contracts as leave_contracts
from enterprise_employee_agent.leave.contracts import (
    COMMAND_SPECS,
    ERROR_MESSAGES,
    ROLE_PROJECTION_FIELDS,
    TRANSITIONS,
    ActorRole,
    AuditEvent,
    CommandName,
    ConfirmationEnvelope,
    ConfirmSubmitInput,
    CreateDraftInput,
    DemoAccessManifest,
    EmployeeLeaveProjection,
    HrLeaveProjection,
    LeaveRequest,
    LeaveRequestPayload,
    LeaveStatus,
    ManagerLeaveProjection,
    RequestType,
    StartProcessingInput,
    UpdateDraftInput,
    WorkflowError,
    WorkflowErrorCode,
    bind_server_command,
    build_audit_event,
    build_leave_preview,
    command_fingerprint,
    load_demo_access_manifest,
    payload_digest,
)

FIXTURE_PATH = Path("data/synthetic_protected/demo-access-v1.json")


def test_demo_access_fixture_defines_roles_relationships_and_denials() -> None:
    manifest = load_demo_access_manifest(FIXTURE_PATH)

    assert {identity.role for identity in manifest.identities} == set(ActorRole)
    assert {rule.role for rule in manifest.permission_rules} == set(ActorRole)
    assert (
        len([identity for identity in manifest.identities if identity.role is ActorRole.EMPLOYEE])
        >= 2
    )
    assert {case.reason for case in manifest.negative_cases} >= {
        "cross_employee_access",
        "non_report_manager_access",
        "employee_hr_action",
    }
    by_reason = {case.reason: case for case in manifest.negative_cases}
    assert (
        by_reason["cross_employee_access"].actor_id
        != by_reason["cross_employee_access"].target_employee_id
    )
    assert (
        by_reason["employee_hr_action"].actor_id
        == by_reason["employee_hr_action"].target_employee_id
    )


def test_demo_access_fixture_rejects_duplicate_identity() -> None:
    raw = load_demo_access_manifest(FIXTURE_PATH).model_dump(mode="json")
    raw["identities"].append(raw["identities"][0])

    with pytest.raises(ValidationError, match="identity_id values must be unique"):
        DemoAccessManifest.model_validate(raw)

    missing_hr = load_demo_access_manifest(FIXTURE_PATH).model_dump(mode="json")
    missing_hr["identities"] = [
        identity for identity in missing_hr["identities"] if identity["role"] != "hr"
    ]
    with pytest.raises(ValidationError, match="at least one HR"):
        DemoAccessManifest.model_validate(missing_hr)


def test_permission_manifest_matches_command_contract() -> None:
    manifest = load_demo_access_manifest(FIXTURE_PATH)
    by_role = {rule.role: rule for rule in manifest.permission_rules}

    assert by_role[ActorRole.EMPLOYEE].request_scope == "own"
    assert by_role[ActorRole.MANAGER].request_scope == "direct_reports"
    assert by_role[ActorRole.MANAGER].allowed_commands == frozenset()
    assert by_role[ActorRole.HR].request_scope == "all"
    for command, spec in COMMAND_SPECS.items():
        for role in ActorRole:
            assert (command in by_role[role].allowed_commands) is (role in spec.allowed_roles)

    raw = manifest.model_dump(mode="json")
    raw["permission_rules"][0]["request_scope"] = "all"
    with pytest.raises(ValidationError, match="permission scope"):
        DemoAccessManifest.model_validate(raw)


def test_leave_payload_normalizes_and_rejects_invalid_dates() -> None:
    payload = LeaveRequestPayload(
        start_date=date(2026, 10, 5),
        end_date=date(2026, 10, 7),
        request_type=RequestType.CONTINUOUS,
        employee_comment="  Family care  ",
    )

    assert payload.employee_comment == "Family care"

    with pytest.raises(ValidationError):
        LeaveRequestPayload(
            start_date=date(2026, 10, 7),
            end_date=date(2026, 10, 5),
            request_type=RequestType.CONTINUOUS,
        )


def test_confirmation_binds_normalized_payload_version_and_digest() -> None:
    payload = LeaveRequestPayload(
        start_date=date(2026, 10, 5),
        end_date=date(2026, 10, 7),
        request_type=RequestType.INTERMITTENT,
        employee_comment="Schedule discussed with HR",
    )
    digest = payload_digest(payload)
    confirmation = ConfirmationEnvelope(
        request_id="leave-alice-001",
        request_version=3,
        payload_digest=digest,
    )

    assert confirmation.matches(request_id="leave-alice-001", payload=payload, request_version=3)
    assert not confirmation.matches(
        request_id="leave-alice-002", payload=payload, request_version=3
    )
    assert not confirmation.matches(
        request_id="leave-alice-001", payload=payload, request_version=4
    )
    assert not confirmation.matches(
        request_id="leave-alice-001",
        payload=payload.model_copy(update={"employee_comment": "Changed"}),
        request_version=3,
    )


def test_preview_contains_normalized_payload_and_matching_confirmation() -> None:
    request = LeaveRequest(
        request_id="leave-alice-001",
        employee_id="employee-alice",
        status=LeaveStatus.DRAFT,
        version=1,
        payload=LeaveRequestPayload(
            start_date=date(2026, 10, 1),
            end_date=date(2026, 10, 5),
            request_type=RequestType.CONTINUOUS,
            employee_comment="  normalized   comment  ",
        ),
        updated_at=datetime(2026, 9, 21, tzinfo=UTC),
        audit_history=(),
    )

    preview = build_leave_preview(request)

    assert preview.payload.employee_comment == "normalized comment"
    assert preview.confirmation.matches(
        request_id=request.request_id,
        payload=request.payload,
        request_version=request.version,
    )


def test_preview_rejects_a_request_that_is_already_submitted() -> None:
    request = LeaveRequest(
        request_id="leave-alice-001",
        employee_id="employee-alice",
        status=LeaveStatus.SUBMITTED,
        version=2,
        payload=LeaveRequestPayload(
            start_date=date(2026, 10, 1),
            end_date=date(2026, 10, 5),
            request_type=RequestType.CONTINUOUS,
        ),
        updated_at=datetime(2026, 9, 21, tzinfo=UTC),
        audit_history=(),
    )

    with pytest.raises(WorkflowError) as excinfo:
        build_leave_preview(request)

    assert excinfo.value.code is WorkflowErrorCode.INVALID_TRANSITION


def test_state_machine_declares_only_v01_transitions() -> None:
    actual = {(item.source, item.command, item.target) for item in TRANSITIONS}

    assert actual == {
        (LeaveStatus.DRAFT, CommandName.CONFIRM_SUBMIT, LeaveStatus.SUBMITTED),
        (LeaveStatus.DRAFT, CommandName.CANCEL_DRAFT, LeaveStatus.CANCELLED),
        (LeaveStatus.SUBMITTED, CommandName.START_PROCESSING, LeaveStatus.PROCESSING),
        (
            LeaveStatus.SUBMITTED,
            CommandName.REQUEST_CLARIFICATION,
            LeaveStatus.NEEDS_CLARIFICATION,
        ),
        (
            LeaveStatus.NEEDS_CLARIFICATION,
            CommandName.CONFIRM_SUBMIT,
            LeaveStatus.SUBMITTED,
        ),
    }


def test_every_command_has_actor_version_and_idempotency_contract() -> None:
    assert set(COMMAND_SPECS) == set(CommandName)
    assert all(spec.allowed_roles for spec in COMMAND_SPECS.values())
    assert all(spec.requires_idempotency_key for spec in COMMAND_SPECS.values())
    assert all(spec.requires_expected_version for spec in COMMAND_SPECS.values())


def test_command_and_audit_envelopes_validate_boundary_fields() -> None:
    payload = LeaveRequestPayload(
        start_date=date(2026, 10, 5),
        end_date=date(2026, 10, 7),
        request_type=RequestType.CONTINUOUS,
    )
    client_input = CreateDraftInput(
        expected_version=0,
        idempotency_key="create-alice-001",
        payload=payload,
    )
    manifest = load_demo_access_manifest(FIXTURE_PATH)
    command = bind_server_command(
        manifest,
        "employee-alice",
        client_input,
        generated_request_id="leave-alice-001",
    )
    assert command.actor.identity_id == "employee-alice"
    assert command.request_id == "leave-alice-001"
    with pytest.raises(ValueError, match="server-selected actor"):
        bind_server_command(
            manifest,
            "attacker-selected",
            client_input,
            generated_request_id="leave-attacker-001",
        )
    fingerprint = command_fingerprint(command)
    event = build_audit_event(
        command,
        event_id="event-001",
        previous_status=None,
        new_status=LeaveStatus.DRAFT,
        previous_version=0,
        request_version=1,
        occurred_at=datetime(2026, 9, 13, 12, 0, tzinfo=UTC),
    )

    assert event.request_version == 1
    assert event.command_fingerprint == fingerprint
    assert not hasattr(leave_contracts, "CommandContext")
    fake_context = SimpleNamespace(
        actor=manifest.identities[-1],
        request_id="leave-alice-001",
        input=StartProcessingInput(
            request_id="leave-alice-001",
            expected_version=1,
            idempotency_key="process-alice-001",
        ),
    )
    with pytest.raises(TypeError, match="bind_server_command"):
        command_fingerprint(fake_context)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="bind_server_command"):
        build_audit_event(
            fake_context,  # type: ignore[arg-type]
            event_id="event-forged",
            previous_status=LeaveStatus.SUBMITTED,
            new_status=LeaveStatus.PROCESSING,
            previous_version=1,
            request_version=2,
            occurred_at=datetime(2026, 9, 13, 12, 0, tzinfo=UTC),
        )
    with pytest.raises(ValueError, match="expected_version"):
        build_audit_event(
            command,
            event_id="event-wrong-version",
            previous_status=None,
            new_status=LeaveStatus.DRAFT,
            previous_version=1,
            request_version=2,
            occurred_at=datetime(2026, 9, 13, 12, 0, tzinfo=UTC),
        )
    invalid_event = event.model_dump()
    invalid_event["occurred_at"] = datetime(2026, 9, 13, 12, 0)
    with pytest.raises(ValidationError, match="timezone-aware"):
        AuditEvent.model_validate(invalid_event)

    with pytest.raises(ValidationError):
        CreateDraftInput.model_validate(
            {**client_input.model_dump(mode="json"), "actor_id": "hr-harper"}
        )
    with pytest.raises(ValidationError):
        CreateDraftInput.model_validate(
            {**client_input.model_dump(mode="json"), "expected_version": 99}
        )
    with pytest.raises(ValidationError):
        UpdateDraftInput(
            request_id="leave-alice-001",
            expected_version=0,
            idempotency_key="update-alice-001",
            payload=payload,
        )

    assert command_fingerprint(command) == command_fingerprint(
        bind_server_command(
            manifest,
            "employee-alice",
            client_input,
            generated_request_id="leave-alice-002",
        )
    )
    changed_payload = client_input.model_copy(
        update={"payload": payload.model_copy(update={"end_date": date(2026, 10, 8)})}
    )
    assert command_fingerprint(command) != command_fingerprint(
        bind_server_command(
            manifest,
            "employee-alice",
            changed_payload,
            generated_request_id="leave-alice-001",
        )
    )

    existing_a = bind_server_command(
        manifest,
        "hr-harper",
        StartProcessingInput(
            request_id="leave-alice-001",
            expected_version=1,
            idempotency_key="process-alice-001",
        ),
    )
    existing_b = bind_server_command(
        manifest,
        "hr-harper",
        StartProcessingInput(
            request_id="leave-alice-002",
            expected_version=1,
            idempotency_key="process-alice-001",
        ),
    )
    assert command_fingerprint(existing_a) != command_fingerprint(existing_b)
    with pytest.raises(ValueError, match="actor role"):
        bind_server_command(
            manifest,
            "employee-alice",
            StartProcessingInput(
                request_id="leave-alice-001",
                expected_version=1,
                idempotency_key="process-alice-001",
            ),
        )

    with pytest.raises(ValidationError):
        StartProcessingInput(
            request_id="leave\nheader-injection",
            expected_version=1,
            idempotency_key="unsafe\nkey",
        )


def test_confirm_submit_input_requires_matching_envelope_target_and_version() -> None:
    confirmation = ConfirmationEnvelope(
        request_id="leave-alice-001",
        request_version=3,
        payload_digest="a" * 64,
    )
    with pytest.raises(ValidationError, match="request_id"):
        ConfirmSubmitInput(
            request_id="leave-alice-002",
            expected_version=3,
            idempotency_key="submit-alice-001",
            confirmation=confirmation,
        )
    with pytest.raises(ValidationError, match="version"):
        ConfirmSubmitInput(
            request_id="leave-alice-001",
            expected_version=4,
            idempotency_key="submit-alice-001",
            confirmation=confirmation,
        )


def test_audit_event_requires_timezone_and_declared_command() -> None:
    event = AuditEvent(
        event_id="event-001",
        request_id="leave-alice-001",
        actor_id="employee-alice",
        command=CommandName.CONFIRM_SUBMIT,
        previous_status=LeaveStatus.DRAFT,
        new_status=LeaveStatus.SUBMITTED,
        previous_version=1,
        request_version=2,
        idempotency_key="employee-alice:submit:0001",
        command_fingerprint="b" * 64,
        occurred_at=datetime(2026, 10, 1, 12, 0, tzinfo=UTC),
    )
    assert event.occurred_at.tzinfo is UTC

    raw = event.model_dump()
    raw["occurred_at"] = datetime(2026, 10, 1, 12, 0)
    with pytest.raises(ValidationError, match="timezone-aware"):
        AuditEvent.model_validate(raw)

    impossible = event.model_dump()
    impossible.update(
        command=CommandName.CREATE_DRAFT,
        previous_status=LeaveStatus.PROCESSING,
        new_status=LeaveStatus.CANCELLED,
    )
    with pytest.raises(ValidationError, match="audit state pair"):
        AuditEvent.model_validate(impossible)

    impossible_version = event.model_dump()
    impossible_version.update(previous_version=0, request_version=1)
    with pytest.raises(ValidationError, match="positive version"):
        AuditEvent.model_validate(impossible_version)


def test_role_projections_are_exact_and_manager_minimizes_data() -> None:
    assert set(ROLE_PROJECTION_FIELDS) == set(ActorRole)
    assert ROLE_PROJECTION_FIELDS[ActorRole.MANAGER] == frozenset(
        {"request_id", "employee_id", "status", "start_date", "end_date", "request_type"}
    )
    assert "employee_comment" not in ROLE_PROJECTION_FIELDS[ActorRole.MANAGER]
    assert "clarification_question" not in ROLE_PROJECTION_FIELDS[ActorRole.MANAGER]
    assert ROLE_PROJECTION_FIELDS[ActorRole.MANAGER] < ROLE_PROJECTION_FIELDS[ActorRole.HR]
    assert ROLE_PROJECTION_FIELDS[ActorRole.MANAGER] == frozenset(
        ManagerLeaveProjection.model_fields
    )
    assert ROLE_PROJECTION_FIELDS[ActorRole.EMPLOYEE] == frozenset(
        EmployeeLeaveProjection.model_fields
    )
    assert ROLE_PROJECTION_FIELDS[ActorRole.HR] == frozenset(HrLeaveProjection.model_fields)
    assert not issubclass(EmployeeLeaveProjection, ManagerLeaveProjection)
    assert not issubclass(HrLeaveProjection, EmployeeLeaveProjection)
    assert "action_history" in ROLE_PROJECTION_FIELDS[ActorRole.EMPLOYEE]
    assert "audit_history" not in ROLE_PROJECTION_FIELDS[ActorRole.EMPLOYEE]

    common = {
        "request_id": "leave-alice-001",
        "employee_id": "employee-alice",
        "status": LeaveStatus.DRAFT,
        "start_date": date(2026, 10, 7),
        "end_date": date(2026, 10, 5),
        "request_type": RequestType.CONTINUOUS,
    }
    with pytest.raises(ValidationError, match="end_date"):
        ManagerLeaveProjection(**common)
    with pytest.raises(ValidationError):
        ManagerLeaveProjection(
            **{**common, "employee_id": "bad\nheader", "end_date": date(2026, 10, 7)}
        )

    foreign_request_event = AuditEvent(
        event_id="event-foreign-request",
        request_id="leave-bob-999",
        actor_id="employee-alice",
        command=CommandName.CREATE_DRAFT,
        previous_status=None,
        new_status=LeaveStatus.DRAFT,
        previous_version=0,
        request_version=1,
        idempotency_key="create-alice-999",
        command_fingerprint="c" * 64,
        occurred_at=datetime(2026, 9, 13, 12, 0, tzinfo=UTC),
    )
    employee_fields = {
        **common,
        "start_date": date(2026, 10, 5),
        "end_date": date(2026, 10, 7),
        "version": 1,
        "updated_at": datetime(2026, 9, 13, 12, 0, tzinfo=UTC),
    }
    with pytest.raises(ValidationError, match="current request"):
        EmployeeLeaveProjection(
            **employee_fields,
            action_history=(foreign_request_event,),
        )
    with pytest.raises(ValidationError):
        EmployeeLeaveProjection(
            **employee_fields,
            employee_comment="x" * 501,
            action_history=(),
        )

    normalized = EmployeeLeaveProjection(
        **employee_fields,
        employee_comment="  operational   note  ",
        clarification_question="  confirm   dates  ",
        action_history=(),
    )
    assert normalized.employee_comment == "operational note"
    assert normalized.clarification_question == "confirm dates"


def test_error_catalogue_covers_deterministic_safety_failures() -> None:
    assert set(WorkflowErrorCode) >= {
        WorkflowErrorCode.UNAUTHORIZED,
        WorkflowErrorCode.FORBIDDEN,
        WorkflowErrorCode.VERSION_CONFLICT,
        WorkflowErrorCode.STALE_CONFIRMATION,
        WorkflowErrorCode.INVALID_TRANSITION,
        WorkflowErrorCode.IDEMPOTENCY_CONFLICT,
        WorkflowErrorCode.SENSITIVE_CONTENT_REJECTED,
    }
    assert set(ERROR_MESSAGES) == set(WorkflowErrorCode)
    assert all("traceback" not in message.casefold() for message in ERROR_MESSAGES.values())
