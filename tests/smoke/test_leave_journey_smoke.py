"""Offline fake-adapter vertical slice: one full happy-path leave journey (Issue #12).

Exercises the knowledge slice and the leave workflow slice together, end to end, with no
network I/O: ``ScriptedProvider`` stands in for the LLM, and ``SQLiteLeaveRepository`` persists
to a temp-dir database. Every mutation goes through ``bind_server_command`` +
``repository.execute``; every role-facing read goes through ``access_policy.project_for``.
"""

# ANCHOR: Milestone v0.1 smoke coverage assembling Issue #8 (knowledge answer pipeline), #9
# (access policy / projections) and #10 (SQLite storage) into one offline, deterministic path.
# Marked ``smoke`` so ``make eval-smoke`` catches an integration break between those pieces
# without a live model call.

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from conftest import NOW, _run

from enterprise_employee_agent.knowledge.answer import OutcomeKind, answer_question
from enterprise_employee_agent.leave.access_policy import project_for, resolve_identity
from enterprise_employee_agent.leave.contracts import (
    ConfirmSubmitInput,
    CreateDraftInput,
    EmployeeLeaveProjection,
    HrLeaveProjection,
    LeaveRequestPayload,
    LeaveStatus,
    ManagerLeaveProjection,
    ProvideClarificationInput,
    RequestClarificationInput,
    RequestType,
    StartProcessingInput,
    build_leave_preview,
)
from enterprise_employee_agent.llm.contract import AnswerStatus
from enterprise_employee_agent.llm.provider import ModelConfig
from enterprise_employee_agent.llm.scripted import ScriptedProvider

QUESTION = "How long is parental leave?"
US_DOCUMENT_ID = "people-policies/leave-of-absence/us.md"
MODEL = ModelConfig(model_id="test/model", max_tokens=200, timeout_seconds=5.0)
REQUEST_ID = "leave-alice-smoke-001"

_MANAGER_PROJECTION_FIELDS = frozenset(
    {"request_id", "employee_id", "status", "start_date", "end_date", "request_type"}
)


def _payload(*, comment: str) -> LeaveRequestPayload:
    return LeaveRequestPayload(
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 5),
        request_type=RequestType.CONTINUOUS,
        employee_comment=comment,
    )


@pytest.mark.smoke
def test_full_leave_journey_across_knowledge_and_workflow_slices(
    manifest, repository, access_map
) -> None:
    # 1. Knowledge slice, state-isolated: answering a question never touches the leave workflow.
    scripted_answer = json.dumps(
        {
            "status": AnswerStatus.ANSWERED.value,
            "answer_text": "Parental leave is 16 weeks and fully paid.",
            "citations": [US_DOCUMENT_ID],
            "clarifying_question": None,
        }
    )
    provider = ScriptedProvider({QUESTION: scripted_answer})
    outcome = answer_question(
        QUESTION,
        identity=resolve_identity(manifest, "employee-alice"),
        access_map=access_map,
        provider=provider,
        model=MODEL,
    )
    assert outcome.kind is OutcomeKind.ANSWER
    assert outcome.answer is not None and outcome.answer.status is AnswerStatus.ANSWERED
    assert outcome.citations == (US_DOCUMENT_ID,)
    assert repository.get(REQUEST_ID) is None

    # 2. Create draft as employee-alice.
    created = _run(
        repository,
        manifest,
        "employee-alice",
        CreateDraftInput(
            expected_version=0,
            idempotency_key="create-alice-smoke-0001",
            payload=_payload(comment="Family trip"),
        ),
        event_id="event-smoke-0001",
        occurred_at=NOW,
        generated_request_id=REQUEST_ID,
    )
    assert created.status is LeaveStatus.DRAFT
    assert created.version == 1

    # 3. Preview and confirm the draft submission.
    preview = build_leave_preview(created)
    submitted = _run(
        repository,
        manifest,
        "employee-alice",
        ConfirmSubmitInput(
            request_id=created.request_id,
            expected_version=1,
            idempotency_key="submit-alice-smoke-0001",
            confirmation=preview.confirmation,
        ),
        event_id="event-smoke-0002",
        occurred_at=NOW + timedelta(minutes=1),
    )
    assert submitted.status is LeaveStatus.SUBMITTED
    assert submitted.version == 2

    # 4. HR requests clarification.
    needs_clarification = _run(
        repository,
        manifest,
        "hr-harper",
        RequestClarificationInput(
            request_id=created.request_id,
            expected_version=2,
            idempotency_key="clarify-alice-smoke-0001",
            question="Please confirm these dates are consecutive business days.",
        ),
        event_id="event-smoke-0003",
        occurred_at=NOW + timedelta(minutes=2),
    )
    assert needs_clarification.status is LeaveStatus.NEEDS_CLARIFICATION
    assert needs_clarification.version == 3

    # 5. Employee provides clarification, then previews and confirms again.
    clarified = _run(
        repository,
        manifest,
        "employee-alice",
        ProvideClarificationInput(
            request_id=created.request_id,
            expected_version=3,
            idempotency_key="answer-alice-smoke-0001",
            payload=_payload(comment="Confirmed: consecutive business days only"),
        ),
        event_id="event-smoke-0004",
        occurred_at=NOW + timedelta(minutes=3),
    )
    assert clarified.status is LeaveStatus.NEEDS_CLARIFICATION
    assert clarified.version == 4

    second_preview = build_leave_preview(clarified)
    resubmitted = _run(
        repository,
        manifest,
        "employee-alice",
        ConfirmSubmitInput(
            request_id=created.request_id,
            expected_version=4,
            idempotency_key="submit-alice-smoke-0002",
            confirmation=second_preview.confirmation,
        ),
        event_id="event-smoke-0005",
        occurred_at=NOW + timedelta(minutes=4),
    )
    assert resubmitted.status is LeaveStatus.SUBMITTED
    assert resubmitted.version == 5

    # 6. HR starts processing.
    processing = _run(
        repository,
        manifest,
        "hr-harper",
        StartProcessingInput(
            request_id=created.request_id,
            expected_version=5,
            idempotency_key="process-alice-smoke-0001",
        ),
        event_id="event-smoke-0006",
        occurred_at=NOW + timedelta(minutes=5),
    )
    assert processing.status is LeaveStatus.PROCESSING
    assert processing.version == 6

    # 7. Employee projection: only alice's own action history.
    employee_view = project_for(manifest, resolve_identity(manifest, "employee-alice"), processing)
    assert isinstance(employee_view, EmployeeLeaveProjection)
    assert all(event.actor_id == "employee-alice" for event in employee_view.action_history)
    assert len(employee_view.action_history) == 4

    # 8. Manager projection: the minimal field set only, no comment/clarification/audit fields.
    manager_view = project_for(manifest, resolve_identity(manifest, "manager-morgan"), processing)
    assert isinstance(manager_view, ManagerLeaveProjection)
    assert set(type(manager_view).model_fields) == _MANAGER_PROJECTION_FIELDS

    # 9. HR projection: full audit history across every transition.
    hr_view = project_for(manifest, resolve_identity(manifest, "hr-harper"), processing)
    assert isinstance(hr_view, HrLeaveProjection)
    assert len(hr_view.audit_history) == 6
