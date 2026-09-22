"""Full assistant journey through the orchestrator, offline (Issue #13, AC-1, Step 11).

Exercises `leave/assistant.py`'s public functions end to end with a `ScriptedProvider`: a
grounded question with cited evidence, structured field extraction (first incomplete, then
complete), a versioned preview, explicit confirmation, HR clarification built from the grounded
answer's own citations, the employee re-answering through a second field extraction, re-preview,
re-submit, HR processing, and the three `project_for` projections. This complements (does not
replace) `tests/smoke/test_leave_journey_smoke.py`, which covers the same workflow spine driven
by hand-typed fields rather than the Issue #13 orchestrator.
"""

# ANCHOR: Milestone Issue #13 smoke coverage assembling the knowledge answer pipeline
# (`answer_for_actor`), the new field-proposal extraction (`propose_leave_fields`,
# `create_draft_from_proposal`, `provide_clarification_from_fields`) and the Issue #12 workflow
# spine (`bind_server_command`/`repository.execute`, `access_policy.project_for`) into one
# offline, deterministic path. Marked `smoke` so `make eval-smoke` catches an integration break
# between the grounded-answer path and the typed workflow without a live model call.

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from conftest import NOW, _run

from enterprise_employee_agent.leave.access_policy import project_for, resolve_identity
from enterprise_employee_agent.leave.assistant import (
    AssistantOutcomeKind,
    FieldProposalOutcomeKind,
    answer_for_actor,
    build_clarification_request,
    create_draft_from_proposal,
    propose_leave_fields,
    provide_clarification_from_fields,
)
from enterprise_employee_agent.leave.contracts import (
    ConfirmSubmitInput,
    EmployeeLeaveProjection,
    HrLeaveProjection,
    LeaveStatus,
    ManagerLeaveProjection,
    RequestType,
    StartProcessingInput,
)
from enterprise_employee_agent.llm.contract import AnswerStatus
from enterprise_employee_agent.llm.provider import ModelConfig
from enterprise_employee_agent.llm.scripted import ScriptedProvider

QUESTION = "How long is parental leave in the US?"
US_DOCUMENT_ID = "people-policies/leave-of-absence/us.md"
MODEL = ModelConfig(model_id="test/model", max_tokens=200, timeout_seconds=5.0)
REQUEST_ID = "leave-alice-assistant-smoke-001"

_INCOMPLETE_DETAIL_TEXT = "I need leave ending Oct 5 2026, continuous, for a family matter."
_COMPLETE_DETAIL_TEXT = "I need leave from Oct 1 to Oct 5 2026, continuous, for a family matter."
_REANSWER_DETAIL_TEXT = (
    "Confirmed: leave from Oct 1 to Oct 5 2026, continuous, consecutive business days only."
)

_MANAGER_PROJECTION_FIELDS = frozenset(
    {"request_id", "employee_id", "status", "start_date", "end_date", "request_type"}
)


def _field_payload(*, start_date: str | None, comment: str) -> dict[str, object]:
    return {
        "start_date": start_date,
        "end_date": "2026-10-05",
        "request_type": RequestType.CONTINUOUS.value,
        "employee_comment": comment,
    }


@pytest.mark.smoke
def test_full_assistant_journey_across_answer_and_field_proposal_paths(
    manifest, repository, access_map
) -> None:
    # 1. Ask a supported US question through the orchestrator; assert cited evidence and a
    # clarifying question the assistant itself proposed (HR will reuse it in step 5).
    scripted_answer = json.dumps(
        {
            "status": AnswerStatus.ANSWERED.value,
            "answer_text": "Parental leave is 16 weeks and fully paid.",
            "citations": [US_DOCUMENT_ID],
            "clarifying_question": "Please confirm these dates are consecutive business days.",
        }
    )
    answer_provider = ScriptedProvider({QUESTION: scripted_answer})
    answer_outcome = answer_for_actor(
        QUESTION,
        manifest=manifest,
        actor_id="employee-alice",
        access_map=access_map,
        provider=answer_provider,
        model=MODEL,
    )
    assert answer_outcome.kind is AssistantOutcomeKind.ANSWERED
    assert answer_outcome.answer is not None
    assert answer_outcome.answer.citations == (US_DOCUMENT_ID,)

    # 2. First employee message is missing start_date; propose_leave_fields reports it as missing
    # rather than inventing or defaulting it.
    field_provider = ScriptedProvider(
        {
            _INCOMPLETE_DETAIL_TEXT: json.dumps(
                _field_payload(start_date=None, comment="Family matter.")
            ),
            _COMPLETE_DETAIL_TEXT: json.dumps(
                _field_payload(start_date="2026-10-01", comment="Family trip")
            ),
            _REANSWER_DETAIL_TEXT: json.dumps(
                _field_payload(
                    start_date="2026-10-01",
                    comment="Confirmed: consecutive business days only",
                )
            ),
        }
    )
    incomplete_outcome = propose_leave_fields(
        _INCOMPLETE_DETAIL_TEXT,
        manifest=manifest,
        actor_id="employee-alice",
        provider=field_provider,
        model=MODEL,
    )
    assert incomplete_outcome.kind is FieldProposalOutcomeKind.PROPOSED
    assert incomplete_outcome.proposal is not None
    assert incomplete_outcome.proposal.missing_fields() == ("start_date",)
    assert repository.get(REQUEST_ID) is None  # no side effect from an incomplete proposal

    # 3. Second employee message supplies the missing field; the complete proposal creates the
    # draft and returns a versioned, confirmable preview.
    complete_outcome = propose_leave_fields(
        _COMPLETE_DETAIL_TEXT,
        manifest=manifest,
        actor_id="employee-alice",
        provider=field_provider,
        model=MODEL,
    )
    assert complete_outcome.kind is FieldProposalOutcomeKind.PROPOSED
    assert complete_outcome.proposal is not None
    assert complete_outcome.proposal.missing_fields() == ()

    preview = create_draft_from_proposal(
        complete_outcome.proposal,
        repository=repository,
        manifest=manifest,
        actor_id="employee-alice",
        request_id=REQUEST_ID,
        idempotency_key="create-alice-assistant-smoke-0001",
        event_id="event-assistant-smoke-0001",
        occurred_at=NOW,
    )
    assert preview.request_id == REQUEST_ID
    assert preview.request_version == 1

    # 4. Explicit confirm: draft -> submitted.
    submitted = _run(
        repository,
        manifest,
        "employee-alice",
        ConfirmSubmitInput(
            request_id=preview.request_id,
            expected_version=preview.request_version,
            idempotency_key="submit-alice-assistant-smoke-0001",
            confirmation=preview.confirmation,
        ),
        event_id="event-assistant-smoke-0002",
        occurred_at=NOW + timedelta(minutes=1),
    )
    assert submitted.status is LeaveStatus.SUBMITTED
    assert submitted.version == 2

    # 5. HR requests clarification, built from the grounded answer's own citations and
    # clarifying question (not a hand-typed HR message).
    clarification_input = build_clarification_request(
        answer_outcome.answer,
        request_id=submitted.request_id,
        expected_version=submitted.version,
        idempotency_key="clarify-alice-assistant-smoke-0001",
    )
    assert US_DOCUMENT_ID in clarification_input.question
    needs_clarification = _run(
        repository,
        manifest,
        "hr-harper",
        clarification_input,
        event_id="event-assistant-smoke-0003",
        occurred_at=NOW + timedelta(minutes=2),
    )
    assert needs_clarification.status is LeaveStatus.NEEDS_CLARIFICATION
    assert needs_clarification.version == 3

    # 6. Employee re-answers via a second field extraction; the resulting typed payload reaches
    # the clarification through provide_clarification_from_fields, producing a new versioned
    # preview.
    reanswer_outcome = propose_leave_fields(
        _REANSWER_DETAIL_TEXT,
        manifest=manifest,
        actor_id="employee-alice",
        provider=field_provider,
        model=MODEL,
    )
    assert reanswer_outcome.kind is FieldProposalOutcomeKind.PROPOSED
    assert reanswer_outcome.proposal is not None
    assert reanswer_outcome.proposal.missing_fields() == ()

    second_preview = provide_clarification_from_fields(
        reanswer_outcome.proposal.to_payload(),
        repository=repository,
        manifest=manifest,
        actor_id="employee-alice",
        request_id=needs_clarification.request_id,
        expected_version=needs_clarification.version,
        idempotency_key="answer-alice-assistant-smoke-0001",
        event_id="event-assistant-smoke-0004",
        occurred_at=NOW + timedelta(minutes=3),
    )
    assert second_preview.request_version == 4
    assert second_preview.payload.employee_comment == "Confirmed: consecutive business days only"

    # 7. Re-submit: needs_clarification -> submitted.
    resubmitted = _run(
        repository,
        manifest,
        "employee-alice",
        ConfirmSubmitInput(
            request_id=second_preview.request_id,
            expected_version=second_preview.request_version,
            idempotency_key="submit-alice-assistant-smoke-0002",
            confirmation=second_preview.confirmation,
        ),
        event_id="event-assistant-smoke-0005",
        occurred_at=NOW + timedelta(minutes=4),
    )
    assert resubmitted.status is LeaveStatus.SUBMITTED
    assert resubmitted.version == 5

    # 8. HR starts processing.
    processing = _run(
        repository,
        manifest,
        "hr-harper",
        StartProcessingInput(
            request_id=resubmitted.request_id,
            expected_version=resubmitted.version,
            idempotency_key="process-alice-assistant-smoke-0001",
        ),
        event_id="event-assistant-smoke-0006",
        occurred_at=NOW + timedelta(minutes=5),
    )
    assert processing.status is LeaveStatus.PROCESSING
    assert processing.version == 6

    # 9. The three project_for projections.
    employee_view = project_for(manifest, resolve_identity(manifest, "employee-alice"), processing)
    assert isinstance(employee_view, EmployeeLeaveProjection)
    assert all(event.actor_id == "employee-alice" for event in employee_view.action_history)
    assert len(employee_view.action_history) == 4

    manager_view = project_for(manifest, resolve_identity(manifest, "manager-morgan"), processing)
    assert isinstance(manager_view, ManagerLeaveProjection)
    assert set(type(manager_view).model_fields) == _MANAGER_PROJECTION_FIELDS

    hr_view = project_for(manifest, resolve_identity(manifest, "hr-harper"), processing)
    assert isinstance(hr_view, HrLeaveProjection)
    assert len(hr_view.audit_history) == 6
