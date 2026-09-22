"""Leave field extraction contract (Issue #13, D-B). Model output is untrusted data.

Separate from, and independent of, ``llm/contract.py``'s ``AnswerContract``/``answer-v1``: those
stay untouched. This module extracts structured leave fields from the employee's own free text,
with no citation requirement.
"""

# ANCHOR: LeaveFieldProposal is data, never authority. It carries only the values the employee's
# message expressed for start_date, end_date, request_type, and employee_comment — no command
# name, actor, request id, version, idempotency key, or "should I submit" flag. missing_fields()
# is computed by deterministic code from which fields are None at call time; the model may never
# supply a missing_fields key itself (ContractModel's extra="forbid" turns that into a SCHEMA
# violation). A proposal becomes a LeaveRequestPayload only through to_payload(), which
# re-validates through LeaveRequestPayload and raises WorkflowError(VALIDATION_FAILED) rather
# than let a pydantic ValidationError escape untyped; building a command from that payload is
# Step 7's job, not this module's. ViolationKind.CITATION_NOT_RETRIEVED is never produced here —
# field proposals cite no documents — which is correct, not an oversight.

from __future__ import annotations

import json
from datetime import date
from typing import Any, Self

from pydantic import ValidationError, model_validator
from pydantic_core import ErrorDetails

from enterprise_employee_agent.leave.contracts import (
    ContractModel,
    LeaveRequestPayload,
    RequestType,
    WorkflowError,
    WorkflowErrorCode,
)
from enterprise_employee_agent.llm.contract import (
    ContractViolation,
    ViolationKind,
    inline_schema_refs,
)

LEAVE_FIELD_PROPOSAL_SCHEMA_NAME = "leave_field_proposal"

_REQUIRED_FIELD_ORDER = ("start_date", "end_date", "request_type")


class LeaveFieldProposal(ContractModel):
    start_date: date | None
    end_date: date | None
    request_type: RequestType | None
    employee_comment: str | None

    @model_validator(mode="after")
    def validate_date_range(self) -> Self:
        if self.start_date is not None and self.end_date is not None:
            if self.end_date < self.start_date:
                raise ValueError("end_date must be on or after start_date")
        return self

    def missing_fields(self) -> tuple[str, ...]:
        """Names of the required fields currently None, computed from live values only."""
        return tuple(name for name in _REQUIRED_FIELD_ORDER if getattr(self, name) is None)

    def to_payload(self) -> LeaveRequestPayload:
        """Build a LeaveRequestPayload, or raise WorkflowError(VALIDATION_FAILED)."""
        if self.missing_fields():
            raise WorkflowError(WorkflowErrorCode.VALIDATION_FAILED)
        try:
            return LeaveRequestPayload(
                start_date=self.start_date,
                end_date=self.end_date,
                request_type=self.request_type,
                employee_comment=self.employee_comment,
            )
        except ValidationError as error:
            raise WorkflowError(WorkflowErrorCode.VALIDATION_FAILED) from error


# Generated from the model so the schema sent to the provider cannot drift from validation, same
# approach as ANSWER_JSON_SCHEMA at llm/contract.py:93.
LEAVE_FIELD_PROPOSAL_JSON_SCHEMA: dict[str, Any] = inline_schema_refs(
    LeaveFieldProposal.model_json_schema()
)


def _describe_error(item: ErrorDetails) -> str:
    """``field.path: message``; model-level errors have an empty path and keep the message."""
    path = ".".join(str(part) for part in item["loc"])
    return f"{path}: {item['msg']}" if path else item["msg"]


def parse_field_proposal(content: str) -> LeaveFieldProposal:
    """Turn untrusted model text into a LeaveFieldProposal, or raise ContractViolation.

    Two failure stages (no citation-membership check, unlike parse_answer): JSON parse, then
    schema validation.
    """
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as error:
        raise ContractViolation(ViolationKind.INVALID_JSON, str(error)) from error
    try:
        return LeaveFieldProposal.model_validate(payload)
    except ValidationError as error:
        messages = "; ".join(_describe_error(item) for item in error.errors())
        raise ContractViolation(ViolationKind.SCHEMA, messages) from error
