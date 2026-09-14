"""Validated answer contract returned by the model (Issue #8).

Model output is untrusted. It is parsed as JSON, validated into ``AnswerContract``, and every
citation must be one of the document IDs retrieved for this question. A violation fails the
case. v0.1 does no retry or repair (decision 0004).
"""

# ANCHOR: The answer contract sent to and validated from the model. AnswerContract is the single
# authoritative schema: ANSWER_JSON_SCHEMA is generated from it (never hand-written) for
# structured-output requests (Task 4). parse_answer() is the boundary function later tasks
# (answer pipeline, Task 5) call: it turns untrusted model text into an AnswerContract or raises
# ContractViolation, checking JSON parse, schema validation (the detail keeps each error's field
# path, final review T3), and citation membership in that order. inline_schema_refs() resolves
# local $ref/$defs so the generated schema carries no references (final review I3: some
# non-OpenAI strict structured-output implementations reject them).

from __future__ import annotations

import copy
import json
from collections.abc import Collection
from enum import StrEnum
from typing import Any, Self

from pydantic import ValidationError, model_validator
from pydantic_core import ErrorDetails

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


_LOCAL_REF_PREFIX = "#/$defs/"


def inline_schema_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``schema`` with every local ``#/$defs/<name>`` reference inlined.

    Sibling keywords next to a ``$ref`` are kept after the resolved definition's own keys. The
    ``$defs`` block is dropped. Non-local or unknown references raise ``ValueError``.
    """
    definitions = schema.get("$defs", {})

    def resolve(node: object, trail: tuple[str, ...]) -> object:
        if isinstance(node, list):
            return [resolve(item, trail) for item in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            reference = node["$ref"]
            name = reference.removeprefix(_LOCAL_REF_PREFIX) if isinstance(reference, str) else ""
            if not isinstance(reference, str) or name == reference or name not in definitions:
                raise ValueError(f"unsupported schema reference: {reference!r}")
            if name in trail:
                raise ValueError(f"recursive schema reference: {reference!r}")
            resolved = resolve(copy.deepcopy(definitions[name]), (*trail, name))
            siblings = {key: resolve(value, trail) for key, value in node.items() if key != "$ref"}
            return {**resolved, **siblings}  # type: ignore[dict-item]
        return {key: resolve(value, trail) for key, value in node.items() if key != "$defs"}

    return resolve(schema, ())  # type: ignore[return-value]


# Generated from the model so the schema sent to the provider cannot drift from validation.
# Checked 2026-09-14 with pydantic in this repo: all four properties required,
# additionalProperties false (ContractModel forbids extras), status inlined as an enum of
# strings (no $ref/$defs), nullable fields as anyOf string/null, no defaults.
ANSWER_JSON_SCHEMA: dict[str, Any] = inline_schema_refs(AnswerContract.model_json_schema())


class ViolationKind(StrEnum):
    INVALID_JSON = "invalid_json"
    SCHEMA = "schema_violation"
    CITATION_NOT_RETRIEVED = "citation_not_retrieved"


class ContractViolation(Exception):
    def __init__(self, kind: ViolationKind, detail: str) -> None:
        super().__init__(f"{kind.value}: {detail}")
        self.kind = kind
        self.detail = detail


def _describe_error(item: ErrorDetails) -> str:
    """``field.path: message``; model-level errors have an empty path and keep the message."""
    path = ".".join(str(part) for part in item["loc"])
    return f"{path}: {item['msg']}" if path else item["msg"]


def parse_answer(content: str, retrieved_ids: Collection[str]) -> AnswerContract:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as error:
        raise ContractViolation(ViolationKind.INVALID_JSON, str(error)) from error
    try:
        answer = AnswerContract.model_validate(payload)
    except ValidationError as error:
        messages = "; ".join(_describe_error(item) for item in error.errors())
        raise ContractViolation(ViolationKind.SCHEMA, messages) from error
    outside = sorted(set(answer.citations) - set(retrieved_ids))
    if outside:
        raise ContractViolation(
            ViolationKind.CITATION_NOT_RETRIEVED,
            "citations outside the retrieved set: " + ", ".join(outside),
        )
    return answer
