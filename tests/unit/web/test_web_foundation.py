"""HTTP contracts for identity, CSRF, errors, and the question page (Issue #14)."""

from __future__ import annotations

import itertools
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from enterprise_employee_agent.app import (
    DemoApplication,
    DemoSettings,
    LeaveForm,
    build_demo_application,
)
from enterprise_employee_agent.leave.contracts import WorkflowErrorCode
from enterprise_employee_agent.llm.provider import (
    AnswerProvider,
    AnswerRequest,
    ProviderError,
    ProviderErrorKind,
    ProviderResponse,
)
from enterprise_employee_agent.llm.scripted import ScriptedProvider
from enterprise_employee_agent.web.errors import http_status_for
from enterprise_employee_agent.web.server import create_app

NOW = datetime(2026, 9, 21, 10, 0, tzinfo=UTC)
ORIGIN = {"origin": "http://testserver"}
QUESTION = "How long is parental leave in the US?"
US_DOC = "people-policies/leave-of-absence/us.md"
FORM = LeaveForm(start_date="2026-10-01", end_date="2026-10-05", request_type="continuous")


def _setup(
    tmp_path: Path, *, provider: AnswerProvider | None = None
) -> tuple[TestClient, DemoApplication]:
    counter = itertools.count(1)
    demo = build_demo_application(
        DemoSettings(database_path=tmp_path / "demo.sqlite", openrouter_api_key=None),
        clock=lambda: NOW,
        id_factory=lambda prefix: f"{prefix}-{next(counter):04d}",
        provider=provider,
    )
    return TestClient(create_app(demo)), demo


def _act_as(client: TestClient, identity_id: str) -> None:
    response = client.post(
        "/identity", data={"identity_id": identity_id}, headers=ORIGIN, follow_redirects=False
    )
    assert response.status_code == 303


class _FailingProvider:
    def complete(self, request: AnswerRequest) -> ProviderResponse:
        raise ProviderError(ProviderErrorKind.HTTP_ERROR, "MARKER-7f3a upstream said no")


def test_root_without_identity_redirects_to_chooser(tmp_path) -> None:
    client, _ = _setup(tmp_path)
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/identity"


def test_identity_chooser_lists_all_identities(tmp_path) -> None:
    client, _ = _setup(tmp_path)
    page = client.get("/identity")
    assert page.status_code == 200
    for name in ("Alice Example", "Morgan Manager", "Harper HR"):
        assert name in page.text


def test_choosing_identity_sets_strict_httponly_cookie(tmp_path) -> None:
    client, _ = _setup(tmp_path)
    response = client.post(
        "/identity", data={"identity_id": "hr-harper"}, headers=ORIGIN, follow_redirects=False
    )
    assert response.status_code == 303
    cookie = response.headers["set-cookie"].lower()
    assert cookie.startswith("demo_identity=hr-harper")
    assert "httponly" in cookie
    assert "samesite=strict" in cookie
    assert "path=/" in cookie


def test_header_shows_identity_role_and_offline_mode(tmp_path) -> None:
    client, _ = _setup(tmp_path)
    _act_as(client, "employee-alice")
    page = client.get("/")
    assert page.status_code == 200
    assert "Alice Example" in page.text
    assert "employee-alice" in page.text
    assert "offline · scripted" in page.text
    assert "not a real HR system" in page.text
    assert QUESTION in page.text  # scripted suggestion


def test_unknown_identity_cookie_is_cleared_and_redirected(tmp_path) -> None:
    client, _ = _setup(tmp_path)
    client.cookies.set("demo_identity", "employee-zed")
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/identity"
    assert 'demo_identity=""' in response.headers["set-cookie"] or (
        "max-age=0" in response.headers["set-cookie"].lower()
    )


def test_every_post_route_rejects_missing_and_foreign_origin(tmp_path) -> None:
    client, demo = _setup(tmp_path)
    preview = demo.create_draft("employee-alice", FORM, "create-alice-01")
    client.cookies.set("demo_identity", "employee-alice")
    form = {
        "identity_id": "hr-harper",
        "question": QUESTION,
        "description": "I need leave.",
        "start_date": "2026-11-01",
        "end_date": "2026-11-02",
        "request_type": "intermittent",
        "employee_comment": "",
        "idempotency_key": "key-csrf-00000001",
        "expected_version": "1",
        "payload_digest": preview.confirmation.payload_digest,
    }
    post_paths = [
        route.path.replace("{request_id}", preview.request_id)
        for route in client.app.routes
        if isinstance(route, APIRoute) and "POST" in route.methods
    ]
    assert "/identity" in post_paths and "/ask" in post_paths
    for path in post_paths:
        for headers in ({}, {"origin": "http://evil.example"}, {"origin": "null"}):
            response = client.post(path, data=form, headers=headers, follow_redirects=False)
            assert response.status_code == 403, (path, headers)
            assert "set-cookie" not in response.headers
    view = demo.request_for("employee-alice", preview.request_id)
    assert view.projection.version == 1
    assert len(demo.requests_for("employee-alice")) == 1


def test_referer_is_accepted_when_origin_is_absent(tmp_path) -> None:
    client, _ = _setup(tmp_path)
    response = client.post(
        "/identity",
        data={"identity_id": "hr-harper"},
        headers={"referer": "http://testserver/identity"},
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_ask_renders_answer_with_evidence_link_and_excerpt(tmp_path) -> None:
    client, _ = _setup(tmp_path)
    _act_as(client, "employee-alice")
    page = client.post("/ask", data={"question": QUESTION}, headers=ORIGIN)
    assert page.status_code == 200
    assert "16 weeks" in page.text
    assert "United States Leave of Absence Policies" in page.text
    assert 'href="https://handbook.gitlab.com/handbook/people-policies/leave-of-absence/us/"' in (
        page.text
    )
    assert "<details>" in page.text


def test_escalated_answer_is_labelled_for_hr_review(tmp_path) -> None:
    client, _ = _setup(tmp_path)
    _act_as(client, "employee-alice")
    page = client.post("/ask", data={"question": "Am I eligible for FMLA leave?"}, headers=ORIGIN)
    assert "This needs HR review" in page.text
    assert "Contact HR" in page.text


def test_provider_failure_detail_never_reaches_html(tmp_path) -> None:
    client, _ = _setup(tmp_path, provider=_FailingProvider())
    _act_as(client, "employee-alice")
    page = client.post("/ask", data={"question": QUESTION}, headers=ORIGIN)
    assert page.status_code == 200
    assert "The assistant is unavailable" in page.text
    assert "MARKER-7f3a" not in page.text
    assert "http_error" not in page.text


def test_model_text_markup_is_escaped(tmp_path) -> None:
    content = json.dumps(
        {
            "status": "answered",
            "answer_text": "<script>alert('x')</script> 16 weeks",
            "citations": [US_DOC],
            "clarifying_question": None,
        }
    )
    client, _ = _setup(tmp_path, provider=ScriptedProvider({QUESTION: content}))
    _act_as(client, "employee-alice")
    page = client.post("/ask", data={"question": QUESTION}, headers=ORIGIN)
    assert "<script>alert(" not in page.text
    assert "&lt;script&gt;alert(" in page.text


def test_unknown_route_uses_the_not_found_page(tmp_path) -> None:
    client, _ = _setup(tmp_path)
    response = client.get("/no-such-page")
    assert response.status_code == 404
    assert "The requested leave item was not found." in response.text


def test_unexpected_exception_is_a_generic_500(tmp_path, monkeypatch) -> None:
    client, demo = _setup(tmp_path)
    _act_as(client, "employee-alice")

    def boom(*args, **kwargs):
        raise RuntimeError("SECRET-TRACE-91")

    monkeypatch.setattr(DemoApplication, "ask", boom)
    quiet = TestClient(client.app, raise_server_exceptions=False)
    quiet.cookies.set("demo_identity", "employee-alice")
    response = quiet.post("/ask", data={"question": QUESTION}, headers=ORIGIN)
    assert response.status_code == 500
    assert "SECRET-TRACE-91" not in response.text
    assert "Traceback" not in response.text


@pytest.mark.parametrize(
    ("code", "status"),
    [
        (WorkflowErrorCode.VALIDATION_FAILED, 422),
        (WorkflowErrorCode.SENSITIVE_CONTENT_REJECTED, 422),
        (WorkflowErrorCode.NOT_FOUND, 404),
        (WorkflowErrorCode.FORBIDDEN, 403),
        (WorkflowErrorCode.VERSION_CONFLICT, 409),
        (WorkflowErrorCode.STALE_CONFIRMATION, 409),
        (WorkflowErrorCode.INVALID_TRANSITION, 409),
        (WorkflowErrorCode.IDEMPOTENCY_CONFLICT, 409),
        (WorkflowErrorCode.STORAGE_UNAVAILABLE, 503),
        (WorkflowErrorCode.UNAUTHORIZED, 303),
    ],
)
def test_error_status_table(code, status) -> None:
    assert http_status_for(code) == status


def test_error_status_table_covers_every_code() -> None:
    for code in WorkflowErrorCode:
        http_status_for(code)


def test_pages_have_labels_for_every_text_control(tmp_path) -> None:
    client, _ = _setup(tmp_path)
    _act_as(client, "employee-alice")
    page = client.get("/").text
    for control_id in re.findall(r'<(?:textarea|select|input)[^>]* id="([a-z_]+)"', page):
        assert f'for="{control_id}"' in page, control_id
