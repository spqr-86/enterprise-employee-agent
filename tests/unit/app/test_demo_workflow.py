"""DemoApplication workflow commands and the single-request read path (Issue #14)."""

from __future__ import annotations

import itertools
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from enterprise_employee_agent.app import (
    DemoApplication,
    DemoSettings,
    LeaveForm,
    build_demo_application,
)
from enterprise_employee_agent.leave.contracts import (
    CommandName,
    EmployeeLeaveProjection,
    HrLeaveProjection,
    LeaveStatus,
    ManagerLeaveProjection,
    WorkflowError,
    WorkflowErrorCode,
)
from enterprise_employee_agent.storage.sqlite import SQLiteLeaveRepository

NOW = datetime(2026, 9, 21, 10, 0, tzinfo=UTC)
FORM = LeaveForm(
    start_date="2026-10-01",
    end_date="2026-10-05",
    request_type="continuous",
    employee_comment="Family matter.",
)


def _demo(tmp_path: Path) -> DemoApplication:
    counter = itertools.count(1)
    return build_demo_application(
        DemoSettings(database_path=tmp_path / "demo.sqlite", openrouter_api_key=None),
        clock=lambda: NOW,
        id_factory=lambda prefix: f"{prefix}-{next(counter):04d}",
    )


def _code(error: pytest.ExceptionInfo[WorkflowError]) -> WorkflowErrorCode:
    return error.value.code


def _submitted(demo: DemoApplication, actor_id: str = "employee-alice") -> str:
    preview = demo.create_draft(actor_id, FORM, f"create-{actor_id}")
    demo.confirm(
        actor_id,
        preview.request_id,
        preview.request_version,
        preview.confirmation.payload_digest,
        f"confirm-{actor_id}",
    )
    return preview.request_id


def test_create_draft_generates_ids_server_side_and_returns_version_one(tmp_path) -> None:
    preview = _demo(tmp_path).create_draft("employee-alice", FORM, "create-alice-01")
    assert preview.request_id == "leave-0001"
    assert preview.request_version == 1
    assert preview.payload.employee_comment == "Family matter."


def test_invalid_form_is_validation_failed(tmp_path) -> None:
    bad = LeaveForm(start_date="2026-10-05", end_date="2026-10-01", request_type="continuous")
    with pytest.raises(WorkflowError) as error:
        _demo(tmp_path).create_draft("employee-alice", bad, "create-alice-01")
    assert _code(error) is WorkflowErrorCode.VALIDATION_FAILED


def test_invalid_idempotency_key_is_validation_failed(tmp_path) -> None:
    with pytest.raises(WorkflowError) as error:
        _demo(tmp_path).create_draft("employee-alice", FORM, "short")
    assert _code(error) is WorkflowErrorCode.VALIDATION_FAILED


def test_unknown_actor_is_unauthorized_before_any_write(tmp_path) -> None:
    demo = _demo(tmp_path)
    with pytest.raises(WorkflowError) as error:
        demo.create_draft("employee-zed", FORM, "create-zed-0001")
    assert _code(error) is WorkflowErrorCode.UNAUTHORIZED


def test_manager_cannot_create_a_draft(tmp_path) -> None:
    with pytest.raises(WorkflowError) as error:
        _demo(tmp_path).create_draft("manager-morgan", FORM, "create-morgan-01")
    assert _code(error) is WorkflowErrorCode.FORBIDDEN


def test_employee_draft_view_has_preview_and_draft_actions(tmp_path) -> None:
    demo = _demo(tmp_path)
    preview = demo.create_draft("employee-alice", FORM, "create-alice-01")
    view = demo.request_for("employee-alice", preview.request_id)
    assert isinstance(view.projection, EmployeeLeaveProjection)
    assert view.preview == preview
    assert view.actions == {
        CommandName.UPDATE_DRAFT,
        CommandName.CANCEL_DRAFT,
        CommandName.CONFIRM_SUBMIT,
    }


def test_confirm_submits_and_hr_sees_processing_actions(tmp_path) -> None:
    demo = _demo(tmp_path)
    request_id = _submitted(demo)
    view = demo.request_for("hr-harper", request_id)
    assert isinstance(view.projection, HrLeaveProjection)
    assert view.projection.status is LeaveStatus.SUBMITTED
    assert len(view.projection.audit_history) == 2
    assert view.preview is None
    assert view.actions == {CommandName.START_PROCESSING, CommandName.REQUEST_CLARIFICATION}


def test_manager_sees_only_the_manager_projection_and_no_actions(tmp_path) -> None:
    demo = _demo(tmp_path)
    request_id = _submitted(demo)
    view = demo.request_for("manager-morgan", request_id)
    assert isinstance(view.projection, ManagerLeaveProjection)
    assert view.actions == frozenset()
    assert view.preview is None


def test_out_of_scope_and_missing_requests_look_the_same(tmp_path) -> None:
    demo = _demo(tmp_path)
    request_id = _submitted(demo)
    for actor_id, target in (
        ("manager-riley", request_id),
        ("employee-bob", request_id),
        ("employee-alice", "leave-9999"),
        ("employee-alice", "../not an id"),
    ):
        with pytest.raises(WorkflowError) as error:
            demo.request_for(actor_id, target)
        assert _code(error) is WorkflowErrorCode.NOT_FOUND


def test_update_then_old_confirmation_is_stale(tmp_path) -> None:
    demo = _demo(tmp_path)
    first = demo.create_draft("employee-alice", FORM, "create-alice-01")
    changed = LeaveForm(start_date="2026-10-01", end_date="2026-10-06", request_type="continuous")
    second = demo.update_draft("employee-alice", first.request_id, 1, changed, "update-alice-01")
    assert second.request_version == 2
    with pytest.raises(WorkflowError) as error:
        demo.confirm(
            "employee-alice",
            first.request_id,
            first.request_version,
            first.confirmation.payload_digest,
            "confirm-alice-01",
        )
    assert _code(error) is WorkflowErrorCode.STALE_CONFIRMATION


def test_cancel_draft_returns_cancelled_projection(tmp_path) -> None:
    demo = _demo(tmp_path)
    preview = demo.create_draft("employee-alice", FORM, "create-alice-01")
    projection = demo.cancel_draft("employee-alice", preview.request_id, 1, "cancel-alice-01")
    assert projection.status is LeaveStatus.CANCELLED


def test_clarification_round_trip(tmp_path) -> None:
    demo = _demo(tmp_path)
    request_id = _submitted(demo)
    asked = demo.hr_clarify("hr-harper", request_id, 2, "Confirm the end date.", "clarify-hr-01")
    assert asked.status is LeaveStatus.NEEDS_CLARIFICATION

    view = demo.request_for("employee-alice", request_id)
    assert view.projection.clarification_question == "Confirm the end date."
    assert CommandName.PROVIDE_CLARIFICATION in view.actions

    answered = demo.employee_clarify("employee-alice", request_id, 3, FORM, "answer-alice-01")
    assert answered.request_version == 4
    resubmitted = demo.confirm(
        "employee-alice",
        request_id,
        answered.request_version,
        answered.confirmation.payload_digest,
        "confirm-alice-02",
    )
    assert resubmitted.status is LeaveStatus.SUBMITTED
    started = demo.hr_start("hr-harper", request_id, 5, "start-hr-0001")
    assert started.status is LeaveStatus.PROCESSING


def test_blank_hr_question_is_validation_failed(tmp_path) -> None:
    demo = _demo(tmp_path)
    request_id = _submitted(demo)
    with pytest.raises(WorkflowError) as error:
        demo.hr_clarify("hr-harper", request_id, 2, "   ", "clarify-hr-01")
    assert _code(error) is WorkflowErrorCode.VALIDATION_FAILED


def test_employee_cannot_start_processing(tmp_path) -> None:
    demo = _demo(tmp_path)
    request_id = _submitted(demo)
    with pytest.raises(WorkflowError) as error:
        demo.hr_start("employee-alice", request_id, 2, "start-alice-01")
    assert _code(error) is WorkflowErrorCode.FORBIDDEN


def test_same_key_same_data_replays_and_different_data_conflicts(tmp_path) -> None:
    demo = _demo(tmp_path)
    first = demo.create_draft("employee-alice", FORM, "create-alice-01")
    again = demo.create_draft("employee-alice", FORM, "create-alice-01")
    assert again.request_id == first.request_id
    other = LeaveForm(start_date="2026-11-01", end_date="2026-11-02", request_type="intermittent")
    with pytest.raises(WorkflowError) as error:
        demo.create_draft("employee-alice", other, "create-alice-01")
    assert _code(error) is WorkflowErrorCode.IDEMPOTENCY_CONFLICT


def test_sqlite_errors_become_storage_unavailable(tmp_path, monkeypatch) -> None:
    demo = _demo(tmp_path)

    def broken(*args, **kwargs):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(SQLiteLeaveRepository, "execute", broken)
    monkeypatch.setattr(SQLiteLeaveRepository, "get", broken)
    with pytest.raises(WorkflowError) as error:
        demo.create_draft("employee-alice", FORM, "create-alice-01")
    assert _code(error) is WorkflowErrorCode.STORAGE_UNAVAILABLE
    with pytest.raises(WorkflowError) as error:
        demo.request_for("employee-alice", "leave-0001")
    assert _code(error) is WorkflowErrorCode.STORAGE_UNAVAILABLE
