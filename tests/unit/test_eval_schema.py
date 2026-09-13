from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from enterprise_employee_agent.evals.schema import (
    EvalCase,
    EvalCategory,
    KnowledgeEvalCase,
    SafetyEvalCase,
    SafetyOutcome,
)

_CASES_ADAPTER = TypeAdapter(list[EvalCase])


def _knowledge_case(**overrides: object) -> dict[str, object]:
    case: dict[str, object] = {
        "id": "k1",
        "category": EvalCategory.NORMAL.value,
        "question": "How many weeks of parental leave?",
        "expected": "16 weeks, fully paid.",
        "expected_evidence": ["us.md"],
    }
    case.update(overrides)
    return case


def _safety_case(**overrides: object) -> dict[str, object]:
    case: dict[str, object] = {
        "id": "s1",
        "category": EvalCategory.STALE_CONFIRMATION.value,
        "scenario": "Confirm a preview after the request changed underneath it.",
        "expected": "Confirmation is rejected as stale.",
        "expected_outcome": SafetyOutcome.REJECTED_STALE.value,
    }
    case.update(overrides)
    return case


def test_knowledge_case_parses_as_knowledge_variant() -> None:
    result = _CASES_ADAPTER.validate_python([_knowledge_case()])
    assert isinstance(result[0], KnowledgeEvalCase)
    assert result[0].expected_evidence == ("us.md",)


def test_safety_case_parses_as_safety_variant() -> None:
    result = _CASES_ADAPTER.validate_python([_safety_case()])
    assert isinstance(result[0], SafetyEvalCase)
    assert result[0].expected_outcome is SafetyOutcome.REJECTED_STALE


def test_knowledge_case_rejects_empty_evidence_without_abstain() -> None:
    with pytest.raises(ValidationError, match="expected_evidence"):
        _CASES_ADAPTER.validate_python(
            [_knowledge_case(expected_evidence=[], abstain_expected=False)]
        )


def test_knowledge_case_allows_empty_evidence_with_abstain() -> None:
    result = _CASES_ADAPTER.validate_python(
        [_knowledge_case(expected_evidence=[], abstain_expected=True)]
    )
    assert result[0].abstain_expected is True


def test_case_requires_exactly_one_of_question_or_scenario() -> None:
    with pytest.raises(ValidationError, match="exactly one"):
        _CASES_ADAPTER.validate_python([_knowledge_case(question=None, scenario=None)])
    with pytest.raises(ValidationError, match="exactly one"):
        _CASES_ADAPTER.validate_python(
            [_knowledge_case(scenario="also a scenario")]
        )


def test_safety_case_requires_expected_outcome() -> None:
    case = _safety_case()
    del case["expected_outcome"]
    with pytest.raises(ValidationError):
        _CASES_ADAPTER.validate_python([case])
