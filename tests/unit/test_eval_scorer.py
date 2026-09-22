from __future__ import annotations

from enterprise_employee_agent.evals.schema import (
    EvalCategory,
    KnowledgeEvalCase,
    SafetyEvalCase,
    SafetyOutcome,
)
from enterprise_employee_agent.evals.scorer import (
    build_report,
    score_knowledge_case,
    score_safety_case,
)


def _knowledge_case(**overrides: object) -> KnowledgeEvalCase:
    fields: dict[str, object] = {
        "id": "k1",
        "category": EvalCategory.NORMAL,
        "question": "q",
        "expected": "e",
        "expected_evidence": ("doc-a", "doc-b"),
    }
    fields.update(overrides)
    return KnowledgeEvalCase(**fields)


def _safety_case(**overrides: object) -> SafetyEvalCase:
    fields: dict[str, object] = {
        "id": "s1",
        "category": EvalCategory.STALE_CONFIRMATION,
        "scenario": "s",
        "expected": "e",
        "expected_outcome": SafetyOutcome.REJECTED_STALE,
    }
    fields.update(overrides)
    return SafetyEvalCase(**fields)


def test_knowledge_case_full_recall_passes() -> None:
    result = score_knowledge_case(
        _knowledge_case(), actual_evidence=["doc-a", "doc-b"], abstained=False
    )
    assert result.passed is True
    assert result.recall == 1.0


def test_knowledge_case_partial_recall_fails_but_reports_fraction() -> None:
    result = score_knowledge_case(_knowledge_case(), actual_evidence=["doc-a"], abstained=False)
    assert result.passed is False
    assert result.recall == 0.5


def test_knowledge_case_no_overlap_scores_zero_recall() -> None:
    result = score_knowledge_case(_knowledge_case(), actual_evidence=[], abstained=False)
    assert result.recall == 0.0
    assert result.passed is False


def test_correct_abstention_passes_with_no_recall_value() -> None:
    case = _knowledge_case(expected_evidence=(), abstain_expected=True)
    result = score_knowledge_case(case, actual_evidence=[], abstained=True)
    assert result.passed is True
    assert result.recall is None
    assert result.abstained_correctly is True


def test_fabricated_answer_when_abstain_expected_fails() -> None:
    case = _knowledge_case(expected_evidence=(), abstain_expected=True)
    result = score_knowledge_case(case, actual_evidence=["doc-a"], abstained=False)
    assert result.passed is False
    assert result.abstained_correctly is False


def test_expected_clarification_not_requested_fails_clarification_ok() -> None:
    case = _knowledge_case(expects_clarification=True)
    result = score_knowledge_case(
        case,
        actual_evidence=["doc-a", "doc-b"],
        abstained=False,
        clarification_requested=False,
    )
    assert result.passed is False
    assert result.clarification_ok is False


def test_expected_clarification_requested_passes() -> None:
    case = _knowledge_case(expects_clarification=True)
    result = score_knowledge_case(
        case,
        actual_evidence=["doc-a", "doc-b"],
        abstained=False,
        clarification_requested=True,
    )
    assert result.passed is True
    assert result.clarification_ok is True


def test_clarification_not_expected_leaves_ok_none_and_passed_unchanged() -> None:
    case = _knowledge_case(expects_clarification=False)
    result = score_knowledge_case(
        case,
        actual_evidence=["doc-a", "doc-b"],
        abstained=False,
        clarification_requested=True,
    )
    assert result.passed is True
    assert result.clarification_ok is None


def test_safety_case_matching_outcome_passes() -> None:
    result = score_safety_case(_safety_case(), actual_outcome=SafetyOutcome.REJECTED_STALE)
    assert result.passed is True
    assert result.actual_outcome == "rejected_stale"


def test_safety_case_mismatched_outcome_fails() -> None:
    result = score_safety_case(_safety_case(), actual_outcome=SafetyOutcome.ERROR_SURFACED)
    assert result.passed is False


def test_build_report_includes_zero_case_categories() -> None:
    result = score_knowledge_case(
        _knowledge_case(), actual_evidence=["doc-a", "doc-b"], abstained=False
    )
    report = build_report([result], [])
    by_category = {aggregate.category: aggregate for aggregate in report.knowledge}
    assert by_category[EvalCategory.NORMAL].total == 1
    assert by_category[EvalCategory.NORMAL].passed == 1
    assert by_category[EvalCategory.OUT_OF_SCOPE].total == 0
    assert by_category[EvalCategory.OUT_OF_SCOPE].passed == 0


def test_build_report_carries_safety_results_untouched() -> None:
    safety_result = score_safety_case(_safety_case(), actual_outcome=SafetyOutcome.ERROR_SURFACED)
    report = build_report([], [safety_result])
    assert report.safety_results == (safety_result,)
