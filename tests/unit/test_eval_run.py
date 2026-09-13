from __future__ import annotations

from pathlib import Path

import pytest

from enterprise_employee_agent.evals.run import (
    _score_duplicate_submission,
    _score_forbidden_disclosure,
    _score_prompt_injection,
    _score_role_view,
    _score_stale_confirmation,
    exit_code_for_report,
    main,
)
from enterprise_employee_agent.evals.schema import EvalCategory, SafetyOutcome
from enterprise_employee_agent.evals.scorer import EvalReport, SafetyCaseResult
from enterprise_employee_agent.leave.contracts import load_demo_access_manifest

DEMO_MANIFEST_PATH = Path("data/synthetic_protected/demo-access-v1.json")


@pytest.mark.smoke
def test_main_runs_end_to_end_and_returns_zero(capsys: pytest.CaptureFixture[str]) -> None:
    # 0 here reflects that every safety case in the real dataset currently passes
    # (see exit_code_for_report), not that main() always returns 0 unconditionally.
    exit_code = main([])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Knowledge categories" in captured.out
    assert "Deterministic safety:" in captured.out


def test_exit_code_for_report_is_nonzero_when_a_safety_case_fails() -> None:
    failing = SafetyCaseResult(
        case_id="s1",
        category=EvalCategory.STALE_CONFIRMATION,
        passed=False,
        actual_outcome="error_surfaced",
        expected_outcome="rejected_stale",
    )
    report = EvalReport(knowledge=(), safety_results=(failing,))
    assert exit_code_for_report(report) != 0


def test_exit_code_for_report_is_zero_when_all_safety_cases_pass() -> None:
    passing = SafetyCaseResult(
        case_id="s1",
        category=EvalCategory.STALE_CONFIRMATION,
        passed=True,
        actual_outcome="rejected_stale",
        expected_outcome="rejected_stale",
    )
    report = EvalReport(knowledge=(), safety_results=(passing,))
    assert exit_code_for_report(report) == 0


def test_score_stale_confirmation_detects_version_mismatch() -> None:
    assert _score_stale_confirmation() is SafetyOutcome.REJECTED_STALE


def test_score_duplicate_submission_is_idempotent() -> None:
    manifest = load_demo_access_manifest(DEMO_MANIFEST_PATH)
    assert _score_duplicate_submission(manifest) is SafetyOutcome.IDEMPOTENT_REPLAY


def test_score_prompt_injection_finds_cross_employee_denial() -> None:
    manifest = load_demo_access_manifest(DEMO_MANIFEST_PATH)
    assert _score_prompt_injection(manifest) is SafetyOutcome.REFUSED


def test_score_forbidden_disclosure_manager_projection_has_no_comment_field() -> None:
    assert _score_forbidden_disclosure() is SafetyOutcome.REDACTED


def test_score_role_view_projections_agree() -> None:
    assert _score_role_view() is SafetyOutcome.CONSISTENT_PROJECTION
