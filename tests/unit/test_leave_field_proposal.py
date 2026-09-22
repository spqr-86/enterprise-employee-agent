from __future__ import annotations

import json
from datetime import date

import pytest
from pydantic import ValidationError

from enterprise_employee_agent.leave.contracts import (
    LeaveRequestPayload,
    RequestType,
    WorkflowError,
    WorkflowErrorCode,
)
from enterprise_employee_agent.leave.field_proposal import (
    LEAVE_FIELD_PROPOSAL_JSON_SCHEMA,
    LeaveFieldProposal,
    parse_field_proposal,
)
from enterprise_employee_agent.llm.contract import ContractViolation, ViolationKind


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "start_date": "2026-10-01",
        "end_date": "2026-10-15",
        "request_type": "continuous",
        "employee_comment": "Taking care of a family matter.",
    }
    payload.update(overrides)
    return payload


def test_full_proposal_parses_with_no_missing_fields() -> None:
    proposal = parse_field_proposal(json.dumps(_payload()))
    assert proposal.start_date == date(2026, 10, 1)
    assert proposal.end_date == date(2026, 10, 15)
    assert proposal.request_type is RequestType.CONTINUOUS
    assert proposal.employee_comment == "Taking care of a family matter."
    assert proposal.missing_fields() == ()


def test_missing_start_date_is_computed_not_stored() -> None:
    proposal = parse_field_proposal(json.dumps(_payload(start_date=None)))
    assert proposal.start_date is None
    assert proposal.missing_fields() == ("start_date",)


def test_end_before_start_is_rejected_at_validation_time() -> None:
    with pytest.raises(ValidationError):
        LeaveFieldProposal.model_validate(_payload(start_date="2026-10-15", end_date="2026-10-01"))


def test_non_json_input_is_invalid_json_violation() -> None:
    with pytest.raises(ContractViolation) as excinfo:
        parse_field_proposal("not json {")
    assert excinfo.value.kind is ViolationKind.INVALID_JSON


def test_unknown_request_type_is_a_schema_violation() -> None:
    with pytest.raises(ContractViolation) as excinfo:
        parse_field_proposal(json.dumps(_payload(request_type="sabbatical")))
    assert excinfo.value.kind is ViolationKind.SCHEMA


def test_extra_key_is_a_schema_violation() -> None:
    with pytest.raises(ContractViolation) as excinfo:
        parse_field_proposal(json.dumps(_payload(command="confirm_submit")))
    assert excinfo.value.kind is ViolationKind.SCHEMA
    assert "command" in excinfo.value.detail


def test_model_supplied_missing_fields_key_is_a_schema_violation() -> None:
    with pytest.raises(ContractViolation) as excinfo:
        parse_field_proposal(json.dumps(_payload(missing_fields=["start_date"])))
    assert excinfo.value.kind is ViolationKind.SCHEMA
    assert "missing_fields" in excinfo.value.detail


def test_to_payload_on_complete_valid_proposal_returns_leave_request_payload() -> None:
    proposal = parse_field_proposal(json.dumps(_payload()))
    payload = proposal.to_payload()
    assert isinstance(payload, LeaveRequestPayload)
    assert payload.start_date == proposal.start_date
    assert payload.end_date == proposal.end_date
    assert payload.request_type is proposal.request_type
    assert payload.employee_comment == proposal.employee_comment


def test_to_payload_on_incomplete_proposal_raises_workflow_error() -> None:
    proposal = parse_field_proposal(json.dumps(_payload(start_date=None)))
    with pytest.raises(WorkflowError) as excinfo:
        proposal.to_payload()
    assert excinfo.value.code is WorkflowErrorCode.VALIDATION_FAILED


def test_to_payload_defence_in_depth_never_lets_a_validation_error_escape() -> None:
    # LeaveFieldProposal's own model_validator already rejects end<start at ordinary parse time
    # (invariant 3 above), so this combination cannot reach to_payload() through
    # parse_field_proposal(). model_construct() bypasses validation entirely (the only way to
    # build such an instance, since the model is frozen and validates on construction), letting
    # us exercise to_payload()'s own re-validation as true defence-in-depth: it must still catch
    # LeaveRequestPayload's ValidationError and re-raise WorkflowError, never let it escape.
    proposal = LeaveFieldProposal.model_construct(
        start_date=date(2026, 10, 15),
        end_date=date(2026, 10, 1),
        request_type=RequestType.CONTINUOUS,
        employee_comment=None,
    )
    with pytest.raises(WorkflowError) as excinfo:
        proposal.to_payload()
    assert excinfo.value.code is WorkflowErrorCode.VALIDATION_FAILED


def test_json_schema_is_generated_from_the_model() -> None:
    assert set(LEAVE_FIELD_PROPOSAL_JSON_SCHEMA["properties"]) == set(
        LeaveFieldProposal.model_fields
    )
    assert LEAVE_FIELD_PROPOSAL_JSON_SCHEMA["additionalProperties"] is False
    serialized = json.dumps(LEAVE_FIELD_PROPOSAL_JSON_SCHEMA)
    assert "$ref" not in serialized
    assert "$defs" not in serialized
