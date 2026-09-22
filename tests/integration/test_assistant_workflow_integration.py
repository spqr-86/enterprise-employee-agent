"""Integration coverage for the grounded-answer write path (Issue #13, Step 4 / AC-1).

Exercises the full journey a real caller takes after getting an ``ANSWERED`` outcome from
``answer_for_actor``: submitting typed fields reaches a versioned, confirmable preview, and
confirming it lands the request in ``SUBMITTED``. Every mutation goes through
``bind_server_command`` + ``repository.execute`` (via ``create_draft_from_fields``,
``provide_clarification_from_fields`` and the smoke journey's ``_run`` helper for the confirm
and HR-clarification-request steps); every read the test itself performs goes through
``access_policy.project_for`` (including the digest checks, which rebuild the payload from the
employee's own projection rather than reading ``repository.get`` directly).
"""

# ANCHOR: Covers create_draft_from_fields and provide_clarification_from_fields end to end,
# alongside Step 3's answer_for_actor, to prove the read (answer) and write (draft/preview)
# sides of the leave assistant compose into one caller-driven journey.

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from conftest import NOW, _run, assert_unchanged

from enterprise_employee_agent.leave.access_policy import project_for, resolve_identity
from enterprise_employee_agent.leave.assistant import (
    AssistantOutcomeKind,
    GroundedAnswer,
    answer_for_actor,
    build_clarification_request,
    create_draft_from_fields,
    provide_clarification_from_fields,
)
from enterprise_employee_agent.leave.contracts import (
    ConfirmSubmitInput,
    CreateDraftInput,
    EmployeeLeaveProjection,
    LeaveRequestPayload,
    LeaveStatus,
    RequestClarificationInput,
    RequestType,
    WorkflowError,
    WorkflowErrorCode,
    bind_server_command,
    build_leave_preview,
    payload_digest,
)
from enterprise_employee_agent.llm.contract import AnswerStatus
from enterprise_employee_agent.llm.provider import ModelConfig
from enterprise_employee_agent.llm.scripted import ScriptedProvider

QUESTION = "How long is parental leave in the US?"
US_DOCUMENT_ID = "people-policies/leave-of-absence/us.md"
MODEL = ModelConfig(model_id="test/model", max_tokens=200, timeout_seconds=5.0)
ACTOR_ID = "employee-alice"
REQUEST_ID = "leave-alice-integration-001"


def _payload(*, comment: str) -> LeaveRequestPayload:
    return LeaveRequestPayload(
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 5),
        request_type=RequestType.CONTINUOUS,
        employee_comment=comment,
    )


def _payload_from_projection(projection: EmployeeLeaveProjection) -> LeaveRequestPayload:
    """Rebuild the payload from a role projection, never from a direct ``repository.get``."""
    return LeaveRequestPayload(
        start_date=projection.start_date,
        end_date=projection.end_date,
        request_type=projection.request_type,
        employee_comment=projection.employee_comment,
    )


def test_answer_then_typed_fields_reach_a_versioned_preview(manifest, repository, access_map):
    # 1. Ask a supported US question and assert ANSWERED with citations.
    scripted_answer = json.dumps(
        {
            "status": AnswerStatus.ANSWERED.value,
            "answer_text": "Parental leave is 16 weeks and fully paid.",
            "citations": [US_DOCUMENT_ID],
            "clarifying_question": None,
        }
    )
    provider = ScriptedProvider({QUESTION: scripted_answer})
    outcome = answer_for_actor(
        QUESTION,
        manifest=manifest,
        actor_id=ACTOR_ID,
        access_map=access_map,
        provider=provider,
        model=MODEL,
    )
    assert outcome.kind is AssistantOutcomeKind.ANSWERED
    assert outcome.answer is not None
    assert outcome.answer.citations == (US_DOCUMENT_ID,)

    # 2. Employee supplies typed fields; assert the resulting preview is versioned and its
    # confirmation digest matches the stored payload.
    preview = create_draft_from_fields(
        _payload(comment="Family trip"),
        repository=repository,
        manifest=manifest,
        actor_id=ACTOR_ID,
        request_id=REQUEST_ID,
        idempotency_key="create-alice-integration-0001",
        event_id="event-integration-0001",
        occurred_at=NOW,
    )
    assert preview.request_id == REQUEST_ID
    assert preview.request_version == 1
    draft = repository.get(REQUEST_ID)
    assert draft is not None
    draft_view = project_for(manifest, resolve_identity(manifest, ACTOR_ID), draft)
    assert isinstance(draft_view, EmployeeLeaveProjection)
    assert preview.confirmation.payload_digest == payload_digest(
        _payload_from_projection(draft_view)
    )

    # 3. Confirm the preview: draft -> submitted.
    submitted = _run(
        repository,
        manifest,
        ACTOR_ID,
        ConfirmSubmitInput(
            request_id=preview.request_id,
            expected_version=preview.request_version,
            idempotency_key="submit-alice-integration-0001",
            confirmation=preview.confirmation,
        ),
        event_id="event-integration-0002",
        occurred_at=NOW + timedelta(minutes=1),
    )
    assert submitted.status is LeaveStatus.SUBMITTED

    employee_view = project_for(manifest, resolve_identity(manifest, ACTOR_ID), submitted)
    assert isinstance(employee_view, EmployeeLeaveProjection)
    assert employee_view.status is LeaveStatus.SUBMITTED


def test_provide_clarification_from_fields_reaches_a_new_versioned_preview(
    manifest, repository, access_map
):
    # Reach NEEDS_CLARIFICATION the same way the smoke journey does: create, submit, HR asks.
    created = _run(
        repository,
        manifest,
        ACTOR_ID,
        CreateDraftInput(
            expected_version=0,
            idempotency_key="create-alice-integration-0002",
            payload=_payload(comment="Family trip"),
        ),
        event_id="event-integration-0003",
        occurred_at=NOW,
        generated_request_id="leave-alice-integration-002",
    )
    first_preview = build_leave_preview(created)
    submitted = _run(
        repository,
        manifest,
        ACTOR_ID,
        ConfirmSubmitInput(
            request_id=created.request_id,
            expected_version=1,
            idempotency_key="submit-alice-integration-0002",
            confirmation=first_preview.confirmation,
        ),
        event_id="event-integration-0004",
        occurred_at=NOW + timedelta(minutes=1),
    )
    needs_clarification = _run(
        repository,
        manifest,
        "hr-harper",
        RequestClarificationInput(
            request_id=submitted.request_id,
            expected_version=2,
            idempotency_key="clarify-alice-integration-0001",
            question="Please confirm these dates are consecutive business days.",
        ),
        event_id="event-integration-0005",
        occurred_at=NOW + timedelta(minutes=2),
    )
    assert needs_clarification.status is LeaveStatus.NEEDS_CLARIFICATION

    # Employee re-supplies typed fields via provide_clarification_from_fields; assert the
    # resulting preview is a new version whose digest matches the newly stored payload.
    preview = provide_clarification_from_fields(
        _payload(comment="Confirmed: consecutive business days only"),
        repository=repository,
        manifest=manifest,
        actor_id=ACTOR_ID,
        request_id=needs_clarification.request_id,
        expected_version=3,
        idempotency_key="answer-alice-integration-0001",
        event_id="event-integration-0006",
        occurred_at=NOW + timedelta(minutes=3),
    )
    assert preview.request_version == 4
    assert preview.payload.employee_comment == "Confirmed: consecutive business days only"
    clarified = repository.get(needs_clarification.request_id)
    assert clarified is not None
    clarified_view = project_for(manifest, resolve_identity(manifest, ACTOR_ID), clarified)
    assert isinstance(clarified_view, EmployeeLeaveProjection)
    assert preview.confirmation.payload_digest == payload_digest(
        _payload_from_projection(clarified_view)
    )

    # Confirm again: needs_clarification -> submitted.
    resubmitted = _run(
        repository,
        manifest,
        ACTOR_ID,
        ConfirmSubmitInput(
            request_id=preview.request_id,
            expected_version=preview.request_version,
            idempotency_key="submit-alice-integration-0003",
            confirmation=preview.confirmation,
        ),
        event_id="event-integration-0007",
        occurred_at=NOW + timedelta(minutes=4),
    )
    assert resubmitted.status is LeaveStatus.SUBMITTED


def test_employee_cannot_execute_a_built_clarification_request(manifest, repository, access_map):
    """An employee actor is FORBIDDEN from executing ``build_clarification_request``'s output.

    ``REQUEST_CLARIFICATION`` is HR-only (``COMMAND_SPECS``); ``build_clarification_request``
    itself does no role checking (D-D), so the rejection must come from
    ``bind_server_command`` and be a typed ``WorkflowError`` (Step 1's fix), not an untyped
    exception. The stored request must be untouched by the rejected attempt.
    """
    created = _run(
        repository,
        manifest,
        ACTOR_ID,
        CreateDraftInput(
            expected_version=0,
            idempotency_key="create-alice-integration-0004",
            payload=_payload(comment="Family trip"),
        ),
        event_id="event-integration-0008",
        occurred_at=NOW,
        generated_request_id="leave-alice-integration-003",
    )
    first_preview = build_leave_preview(created)
    submitted = _run(
        repository,
        manifest,
        ACTOR_ID,
        ConfirmSubmitInput(
            request_id=created.request_id,
            expected_version=1,
            idempotency_key="submit-alice-integration-0004",
            confirmation=first_preview.confirmation,
        ),
        event_id="event-integration-0009",
        occurred_at=NOW + timedelta(minutes=1),
    )
    assert submitted.status is LeaveStatus.SUBMITTED
    before = repository.get(submitted.request_id)
    assert before is not None

    answer = GroundedAnswer(
        kind=AssistantOutcomeKind.ANSWERED,
        status=AnswerStatus.ANSWERED,
        answer_text="Parental leave is 16 weeks and fully paid.",
        citations=(US_DOCUMENT_ID,),
        clarifying_question="Please confirm these dates are consecutive business days.",
        retrieved_ids=(US_DOCUMENT_ID,),
    )
    command_input = build_clarification_request(
        answer,
        request_id=submitted.request_id,
        expected_version=submitted.version,
        idempotency_key="clarify-alice-integration-0001",
    )
    assert isinstance(command_input, RequestClarificationInput)

    with pytest.raises(WorkflowError) as excinfo:
        bind_server_command(manifest, ACTOR_ID, command_input)
    assert excinfo.value.code is WorkflowErrorCode.FORBIDDEN

    assert_unchanged(repository, submitted.request_id, before)
