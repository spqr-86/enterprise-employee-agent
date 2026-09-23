"""HTTP contracts for leave request pages (Issue #14)."""

from __future__ import annotations

import itertools
import re
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from enterprise_employee_agent.app import (
    DemoApplication,
    DemoSettings,
    LeaveForm,
    build_demo_application,
)
from enterprise_employee_agent.leave.contracts import LeaveStatus
from enterprise_employee_agent.web.server import create_app

NOW = datetime(2026, 9, 21, 10, 0, tzinfo=UTC)
ORIGIN = {"origin": "http://testserver"}
DESCRIPTION = "I need continuous leave from 2026-10-01 to 2026-10-05 for a family matter."
FIELDS = {
    "start_date": "2026-10-01",
    "end_date": "2026-10-05",
    "request_type": "continuous",
    "employee_comment": "Family matter.",
}
FORM = LeaveForm(**FIELDS)


def _setup(tmp_path: Path) -> tuple[TestClient, DemoApplication]:
    counter = itertools.count(1)
    demo = build_demo_application(
        DemoSettings(database_path=tmp_path / "demo.sqlite", openrouter_api_key=None),
        clock=lambda: NOW,
        id_factory=lambda prefix: f"{prefix}-{next(counter):04d}",
    )
    return TestClient(create_app(demo)), demo


def _act_as(client: TestClient, identity_id: str) -> None:
    response = client.post(
        "/identity", data={"identity_id": identity_id}, headers=ORIGIN, follow_redirects=False
    )
    assert response.status_code == 303


def _form(html: str, action: str) -> dict[str, str]:
    match = re.search(rf'<form method="post" action="{re.escape(action)}">.*?</form>', html, re.S)
    assert match is not None, f"no form posting to {action}"
    return dict(re.findall(r'<input type="hidden" name="([a-z_]+)" value="([^"]*)">', match[0]))


def _post(client: TestClient, path: str, data: dict[str, str]):
    return client.post(path, data=data, headers=ORIGIN, follow_redirects=False)


def _submitted(demo: DemoApplication) -> str:
    preview = demo.create_draft("employee-alice", FORM, "create-alice-01")
    demo.confirm(
        "employee-alice", preview.request_id, 1, preview.confirmation.payload_digest, "confirm-01"
    )
    return preview.request_id


def test_propose_prefills_editable_form_with_fresh_key(tmp_path) -> None:
    client, _ = _setup(tmp_path)
    _act_as(client, "employee-alice")
    assert client.get("/requests/new").status_code == 200
    page = client.post("/requests/propose", data={"description": DESCRIPTION}, headers=ORIGIN)
    assert page.status_code == 200
    assert 'value="2026-10-01"' in page.text
    assert 'value="2026-10-05"' in page.text
    assert re.fullmatch(r"[0-9a-f]{32}", _form(page.text, "/requests")["idempotency_key"])
    assert "actor_id" not in page.text


def test_propose_failure_shows_empty_form_with_manual_note(tmp_path) -> None:
    client, _ = _setup(tmp_path)
    _act_as(client, "employee-alice")
    page = client.post("/requests/propose", data={"description": "Time off pls"}, headers=ORIGIN)
    assert page.status_code == 200
    assert "Fill in the fields manually" in page.text
    assert 'id="start_date" name="start_date" type="date" value=""' in page.text


def test_create_redirects_to_preview_with_version_and_digest(tmp_path) -> None:
    client, demo = _setup(tmp_path)
    _act_as(client, "employee-alice")
    response = _post(client, "/requests", {**FIELDS, "idempotency_key": "key-create-000001"})
    assert response.status_code == 303
    assert response.headers["location"] == "/requests/leave-0001"
    page = client.get("/requests/leave-0001")
    preview = demo.request_for("employee-alice", "leave-0001").preview
    assert "Confirm and submit version 1" in page.text
    confirm = _form(page.text, "/requests/leave-0001/confirm")
    assert confirm["expected_version"] == "1"
    assert confirm["payload_digest"] == preview.confirmation.payload_digest
    assert set(confirm) == {"idempotency_key", "expected_version", "payload_digest"}


def test_actor_id_form_field_is_ignored(tmp_path) -> None:
    client, demo = _setup(tmp_path)
    _act_as(client, "employee-alice")
    data = {**FIELDS, "idempotency_key": "key-create-000001", "actor_id": "employee-bob"}
    assert _post(client, "/requests", data).status_code == 303
    assert demo.requests_for("employee-bob") == ()
    assert len(demo.requests_for("employee-alice")) == 1


def test_invalid_fields_rerender_form_with_values_and_422(tmp_path) -> None:
    client, _ = _setup(tmp_path)
    _act_as(client, "employee-alice")
    data = {**FIELDS, "end_date": "2026-09-01", "idempotency_key": "key-create-000001"}
    page = _post(client, "/requests", data)
    assert page.status_code == 422
    assert "The request data is invalid." in page.text
    assert 'value="2026-09-01"' in page.text
    assert 'aria-describedby="form-error"' in page.text


def test_same_key_replays_and_different_data_conflicts(tmp_path) -> None:
    client, _ = _setup(tmp_path)
    _act_as(client, "employee-alice")
    data = {**FIELDS, "idempotency_key": "key-create-000001"}
    first = _post(client, "/requests", data)
    second = _post(client, "/requests", data)
    assert first.headers["location"] == second.headers["location"]
    conflict = _post(client, "/requests", {**data, "end_date": "2026-10-09"})
    assert conflict.status_code == 409
    assert "This operation key was used for different data." in conflict.text


def test_foreign_and_missing_requests_render_the_same_404(tmp_path) -> None:
    client, demo = _setup(tmp_path)
    request_id = _submitted(demo)
    _act_as(client, "employee-bob")
    foreign = client.get(f"/requests/{request_id}")
    missing = client.get("/requests/leave-9999")
    assert foreign.status_code == missing.status_code == 404
    assert foreign.text == missing.text


def test_manager_cannot_create_requests(tmp_path) -> None:
    client, _ = _setup(tmp_path)
    _act_as(client, "manager-morgan")
    response = _post(client, "/requests", {**FIELDS, "idempotency_key": "key-create-000001"})
    assert response.status_code == 403
    assert "This action is not available to the selected identity." in response.text


def test_stale_confirmation_is_409_with_fresh_preview(tmp_path) -> None:
    client, _ = _setup(tmp_path)
    _act_as(client, "employee-alice")
    _post(client, "/requests", {**FIELDS, "idempotency_key": "key-create-000001"})
    old_confirm = _form(client.get("/requests/leave-0001").text, "/requests/leave-0001/confirm")
    edit = _form(client.get("/requests/leave-0001/edit").text, "/requests/leave-0001/edit")
    changed = _post(
        client, "/requests/leave-0001/edit", {**edit, **FIELDS, "end_date": "2026-10-06"}
    )
    assert changed.status_code == 303
    stale = _post(client, "/requests/leave-0001/confirm", old_confirm)
    assert stale.status_code == 409
    assert "The preview changed; review and confirm it again." in stale.text
    assert "Confirm and submit version 2" in stale.text


def test_cancel_draft(tmp_path) -> None:
    client, demo = _setup(tmp_path)
    _act_as(client, "employee-alice")
    _post(client, "/requests", {**FIELDS, "idempotency_key": "key-create-000001"})
    cancel = _form(client.get("/requests/leave-0001").text, "/requests/leave-0001/cancel")
    assert _post(client, "/requests/leave-0001/cancel", cancel).status_code == 303
    assert demo.request_for("employee-alice", "leave-0001").projection.status is (
        LeaveStatus.CANCELLED
    )


def test_hr_sees_audit_history_and_can_start_processing(tmp_path) -> None:
    client, demo = _setup(tmp_path)
    request_id = _submitted(demo)
    _act_as(client, "hr-harper")
    listing = client.get("/requests")
    assert request_id in listing.text
    page = client.get(f"/requests/{request_id}")
    assert "Audit history" in page.text
    assert "Family matter." in page.text
    start = _form(page.text, f"/requests/{request_id}/start-processing")
    assert _post(client, f"/requests/{request_id}/start-processing", start).status_code == 303
    assert demo.request_for("hr-harper", request_id).projection.status is LeaveStatus.PROCESSING


def test_hr_list_hides_drafts(tmp_path) -> None:
    client, demo = _setup(tmp_path)
    demo.create_draft("employee-alice", FORM, "create-alice-01")
    _act_as(client, "hr-harper")
    page = client.get("/requests")
    assert "leave-0001" not in page.text
    assert "No requests to show." in page.text


def test_manager_page_renders_only_the_manager_projection(tmp_path) -> None:
    client, demo = _setup(tmp_path)
    request_id = _submitted(demo)
    _act_as(client, "manager-morgan")
    page = client.get(f"/requests/{request_id}")
    assert page.status_code == 200
    assert "submitted" in page.text
    assert "Family matter." not in page.text
    assert "Audit history" not in page.text
    assert f'action="/requests/{request_id}/' not in page.text
    _act_as(client, "manager-riley")
    assert client.get(f"/requests/{request_id}").status_code == 404


def test_hr_blank_clarification_question_is_422_on_the_request_page(tmp_path) -> None:
    client, demo = _setup(tmp_path)
    request_id = _submitted(demo)
    _act_as(client, "hr-harper")
    form = _form(
        client.get(f"/requests/{request_id}").text, f"/requests/{request_id}/clarification-request"
    )
    page = _post(client, f"/requests/{request_id}/clarification-request", {**form, "question": " "})
    assert page.status_code == 422
    assert "The request data is invalid." in page.text


def test_clarification_round_trip_through_forms(tmp_path) -> None:
    client, demo = _setup(tmp_path)
    request_id = _submitted(demo)
    _act_as(client, "hr-harper")
    ask = _form(
        client.get(f"/requests/{request_id}").text, f"/requests/{request_id}/clarification-request"
    )
    response = _post(
        client,
        f"/requests/{request_id}/clarification-request",
        {**ask, "question": "Please confirm the end date."},
    )
    assert response.status_code == 303

    _act_as(client, "employee-alice")
    page = client.get(f"/requests/{request_id}")
    assert "Please confirm the end date." in page.text
    answer = _form(page.text, f"/requests/{request_id}/clarification-response")
    response = _post(
        client,
        f"/requests/{request_id}/clarification-response",
        {**answer, **FIELDS, "end_date": "2026-10-06"},
    )
    assert response.status_code == 303
    page = client.get(f"/requests/{request_id}")
    confirm = _form(page.text, f"/requests/{request_id}/confirm")
    assert _post(client, f"/requests/{request_id}/confirm", confirm).status_code == 303
    assert demo.request_for("employee-alice", request_id).projection.status is (
        LeaveStatus.SUBMITTED
    )
