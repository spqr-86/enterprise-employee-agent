"""Validated answer contract returned by the model (Issue #8).

Model output is untrusted. It is parsed as JSON, validated into ``AnswerContract``, and every
citation must be one of the document IDs retrieved for this question. A violation fails the
case. v0.1 does no retry or repair (decision 0004).
"""

# ANCHOR: The answer contract sent to and validated from the model. AnswerContract is the single
# authoritative schema: ANSWER_JSON_SCHEMA is generated from it (never hand-written) for
# structured-output requests (Task 4). parse_answer() is the boundary function later tasks
# (answer pipeline, Task 5) call: it turns untrusted model text into an AnswerContract or raises
# ContractViolation, checking JSON parse, schema validation, and citation membership in that
# order.

from __future__ import annotations

import json
from collections.abc import Collection
from enum import StrEnum
from typing import Any, Self

from pydantic import ValidationError, model_validator

from enterprise_employee_agent.leave.contracts import ContractModel

ANSWER_SCHEMA_NAME = "answer_contract"


class AnswerStatus(StrEnum):
    ANSWERED = "answered"
    ABSTAINED = "abstained"
    ESCALATED = "escalated"


class AnswerContract(ContractModel):
    status: AnswerStatus
    answer_text: str | None
    citations: tuple[str, ...]
    clarifying_question: str | None

    @model_validator(mode="after")
    def validate_status_fields(self) -> Self:
        if self.status is AnswerStatus.ABSTAINED:
            if self.citations:
                raise ValueError("abstained answers must not cite documents")
            return self
        if self.answer_text is None or not self.answer_text.strip():
            raise ValueError(f"{self.status.value} requires answer_text")
        if not self.citations:
            raise ValueError(f"{self.status.value} requires citations")
        return self


# Generated from the model so the schema sent to the provider cannot drift from validation.
# Checked 2026-09-13 with pydantic in this repo: all four properties required,
# additionalProperties false (ContractModel forbids extras), status as $defs/$ref, nullable
# fields as anyOf string/null, no defaults.
ANSWER_JSON_SCHEMA: dict[str, Any] = AnswerContract.model_json_schema()


class ViolationKind(StrEnum):
    INVALID_JSON = "invalid_json"
    SCHEMA = "schema_violation"
    CITATION_NOT_RETRIEVED = "citation_not_retrieved"


class ContractViolation(Exception):
    def __init__(self, kind: ViolationKind, detail: str) -> None:
        super().__init__(f"{kind.value}: {detail}")
        self.kind = kind
        self.detail = detail


def parse_answer(content: str, retrieved_ids: Collection[str]) -> AnswerContract:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as error:
        raise ContractViolation(ViolationKind.INVALID_JSON, str(error)) from error
    try:
        answer = AnswerContract.model_validate(payload)
    except ValidationError as error:
        messages = "; ".join(item["msg"] for item in error.errors())
        raise ContractViolation(ViolationKind.SCHEMA, messages) from error
    outside = sorted(set(answer.citations) - set(retrieved_ids))
    if outside:
        raise ContractViolation(
            ViolationKind.CITATION_NOT_RETRIEVED,
            "citations outside the retrieved set: " + ", ".join(outside),
        )
    return answer
