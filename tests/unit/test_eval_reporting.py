from __future__ import annotations

from enterprise_employee_agent.evals.reporting import format_report
from enterprise_employee_agent.evals.schema import EvalCategory
from enterprise_employee_agent.evals.scorer import CategoryAggregate, EvalReport, SafetyCaseResult


def test_report_shows_percentage_for_populated_category() -> None:
    report = EvalReport(
        knowledge=(CategoryAggregate(category=EvalCategory.NORMAL, total=4, passed=3),),
        safety_results=(),
    )
    text = format_report(report)
    assert "normal: 3/4 (75%)" in text


def test_report_shows_na_for_zero_case_category() -> None:
    report = EvalReport(
        knowledge=(CategoryAggregate(category=EvalCategory.OUT_OF_SCOPE, total=0, passed=0),),
        safety_results=(),
    )
    text = format_report(report)
    assert "out_of_scope: n/a (0 cases)" in text
    assert "out_of_scope: 0%" not in text


def test_report_marks_safety_section_pass_when_all_pass() -> None:
    safety_result = SafetyCaseResult(
        case_id="s1",
        category=EvalCategory.STALE_CONFIRMATION,
        passed=True,
        actual_outcome="rejected_stale",
        expected_outcome="rejected_stale",
    )
    report = EvalReport(knowledge=(), safety_results=(safety_result,))
    text = format_report(report)
    assert "PASS (1/1)" in text


def test_report_marks_safety_section_fail_and_lists_failing_ids() -> None:
    passing = SafetyCaseResult(
        case_id="s1",
        category=EvalCategory.STALE_CONFIRMATION,
        passed=True,
        actual_outcome="rejected_stale",
        expected_outcome="rejected_stale",
    )
    failing = SafetyCaseResult(
        case_id="s2",
        category=EvalCategory.DUPLICATE_SUBMISSION,
        passed=False,
        actual_outcome="error_surfaced",
        expected_outcome="idempotent_replay",
    )
    report = EvalReport(knowledge=(), safety_results=(passing, failing))
    text = format_report(report)
    assert "FAIL" in text
    assert "s2" in text
    assert "s1" not in text.split("Deterministic safety:")[1].split("\n")[1]


def test_report_shows_na_for_no_safety_cases() -> None:
    report = EvalReport(knowledge=(), safety_results=())
    text = format_report(report)
    assert "Deterministic safety:\n  n/a (0 cases)" in text
