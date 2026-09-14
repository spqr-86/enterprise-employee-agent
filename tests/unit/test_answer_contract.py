from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from enterprise_employee_agent.llm.contract import (
    ANSWER_JSON_SCHEMA,
    AnswerContract,
    AnswerStatus,
    ContractViolation,
    ViolationKind,
    inline_schema_refs,
    parse_answer,
)

US = "people-policies/leave-of-absence/us.md"


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": "answered",
        "answer_text": "16 weeks, fully paid.",
        "citations": [US],
        "clarifying_question": None,
    }
    payload.update(overrides)
    return payload


def test_answered_with_citation_parses() -> None:
    answer = parse_answer(json.dumps(_payload()), [US])
    assert answer.status is AnswerStatus.ANSWERED
    assert answer.citations == (US,)


def test_answered_may_carry_a_clarifying_question() -> None:
    answer = parse_answer(
        json.dumps(_payload(clarifying_question="Which branch of service?")), [US]
    )
    assert answer.clarifying_question == "Which branch of service?"


def test_escalated_requires_citations() -> None:
    with pytest.raises(ValidationError, match="requires citations"):
        AnswerContract.model_validate(_payload(status="escalated", citations=[]))


def test_answered_requires_answer_text() -> None:
    with pytest.raises(ValidationError, match="requires answer_text"):
        AnswerContract.model_validate(_payload(answer_text=None))


def test_abstained_may_omit_text_but_must_not_cite() -> None:
    answer = AnswerContract.model_validate(
        _payload(status="abstained", answer_text=None, citations=[])
    )
    assert answer.status is AnswerStatus.ABSTAINED
    with pytest.raises(ValidationError, match="must not cite"):
        AnswerContract.model_validate(_payload(status="abstained", citations=[US]))


def test_unparseable_json_is_a_violation() -> None:
    with pytest.raises(ContractViolation) as excinfo:
        parse_answer("not json {", [US])
    assert excinfo.value.kind is ViolationKind.INVALID_JSON


def test_missing_field_is_a_schema_violation() -> None:
    payload = _payload()
    del payload["citations"]
    with pytest.raises(ContractViolation) as excinfo:
        parse_answer(json.dumps(payload), [US])
    assert excinfo.value.kind is ViolationKind.SCHEMA


def test_extra_field_is_a_schema_violation() -> None:
    with pytest.raises(ContractViolation) as excinfo:
        parse_answer(json.dumps(_payload(confidence=0.9)), [US])
    assert excinfo.value.kind is ViolationKind.SCHEMA


def test_citation_outside_retrieved_set_is_a_violation() -> None:
    with pytest.raises(ContractViolation) as excinfo:
        parse_answer(json.dumps(_payload()), ["people-policies/leave-of-absence/_index.md"])
    assert excinfo.value.kind is ViolationKind.CITATION_NOT_RETRIEVED
    assert US in excinfo.value.detail


def test_json_schema_is_generated_from_the_model_and_strict_compatible() -> None:
    assert ANSWER_JSON_SCHEMA == inline_schema_refs(AnswerContract.model_json_schema())
    # Strict structured outputs need every property required and no extra properties.
    assert set(ANSWER_JSON_SCHEMA["required"]) == set(AnswerContract.model_fields)
    assert set(ANSWER_JSON_SCHEMA["properties"]) == set(AnswerContract.model_fields)
    assert ANSWER_JSON_SCHEMA["additionalProperties"] is False
    assert '"default"' not in json.dumps(ANSWER_JSON_SCHEMA)
    # Final review I3: no $ref/$defs, which some non-OpenAI strict implementations reject.
    serialized = json.dumps(ANSWER_JSON_SCHEMA)
    assert "$ref" not in serialized
    assert "$defs" not in serialized
    assert ANSWER_JSON_SCHEMA["properties"]["status"]["enum"] == [s.value for s in AnswerStatus]
    assert ANSWER_JSON_SCHEMA["properties"]["status"]["type"] == "string"
    for field in ("answer_text", "clarifying_question"):
        assert ANSWER_JSON_SCHEMA["properties"][field]["anyOf"] == [
            {"type": "string"},
            {"type": "null"},
        ]


def test_inline_schema_refs_resolves_nested_refs_deterministically() -> None:
    schema = {
        "$defs": {
            "Inner": {"type": "string", "enum": ["a"]},
            "Outer": {"type": "object", "properties": {"x": {"$ref": "#/$defs/Inner"}}},
        },
        "type": "object",
        "properties": {
            "o": {"$ref": "#/$defs/Outer", "description": "kept"},
            "items": {"type": "array", "items": {"$ref": "#/$defs/Inner"}},
        },
    }
    before = json.dumps(schema, sort_keys=True)
    result = inline_schema_refs(schema)
    assert json.dumps(schema, sort_keys=True) == before  # input not mutated
    assert result == {
        "type": "object",
        "properties": {
            "o": {
                "type": "object",
                "properties": {"x": {"type": "string", "enum": ["a"]}},
                "description": "kept",
            },
            "items": {"type": "array", "items": {"type": "string", "enum": ["a"]}},
        },
    }
    assert inline_schema_refs(schema) == result
    with pytest.raises(ValueError):
        inline_schema_refs({"properties": {"x": {"$ref": "https://example.com/s.json"}}})
