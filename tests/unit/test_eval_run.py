from __future__ import annotations

import json
from pathlib import Path

import pytest

from enterprise_employee_agent.evals.run import (
    FORBIDDEN_DOCUMENT_PROBE,
    _score_duplicate_submission,
    _score_forbidden_disclosure,
    _score_role_view,
    _score_stale_confirmation,
    calls_model,
    case_prompt,
    deterministic_safety_outcome,
    exit_code_for_report,
    load_scripted_provider,
    main,
    prompt_injection_outcome,
    run_offline,
)
from enterprise_employee_agent.evals.schema import EvalCategory, SafetyOutcome
from enterprise_employee_agent.evals.scorer import EvalReport, SafetyCaseResult
from enterprise_employee_agent.evals.validator import load_cases
from enterprise_employee_agent.knowledge.access import (
    RESTRICTED_FIXTURE_ID,
    load_document_access_map,
)
from enterprise_employee_agent.knowledge.answer import OutcomeKind
from enterprise_employee_agent.knowledge.retrieval import rank_documents
from enterprise_employee_agent.leave.contracts import load_demo_access_manifest
from enterprise_employee_agent.llm.contract import AnswerStatus
from enterprise_employee_agent.llm.scripted import ScriptedProvider

DEMO_MANIFEST_PATH = Path("data/synthetic_protected/demo-access-v1.json")
DATASET_PATH = Path("evals/cases/v0.1.yaml")
SCRIPTED_PATH = Path("tests/fixtures/llm/eval-v0.1-scripted.json")


@pytest.mark.smoke
def test_main_runs_end_to_end_and_returns_zero(capsys: pytest.CaptureFixture[str]) -> None:
    # 0 reflects that every case passes against the scripted responses, not an unconditional 0.
    exit_code = main([])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Knowledge categories" in captured.out
    assert "Deterministic safety:" in captured.out
    assert "PASS (7/7)" in captured.out


def test_exit_code_for_report_is_nonzero_when_a_safety_case_fails() -> None:
    failing = SafetyCaseResult(
        case_id="s1",
        category=EvalCategory.STALE_CONFIRMATION,
        passed=False,
        actual_outcome="error_surfaced",
        expected_outcome="rejected_stale",
    )
    assert exit_code_for_report(EvalReport(knowledge=(), safety_results=(failing,))) != 0


def test_exit_code_for_report_is_zero_when_all_safety_cases_pass() -> None:
    passing = SafetyCaseResult(
        case_id="s1",
        category=EvalCategory.STALE_CONFIRMATION,
        passed=True,
        actual_outcome="rejected_stale",
        expected_outcome="rejected_stale",
    )
    assert exit_code_for_report(EvalReport(knowledge=(), safety_results=(passing,))) == 0


def test_score_stale_confirmation_detects_version_mismatch() -> None:
    assert _score_stale_confirmation() is SafetyOutcome.REJECTED_STALE


def test_score_duplicate_submission_is_idempotent() -> None:
    manifest = load_demo_access_manifest(DEMO_MANIFEST_PATH)
    assert _score_duplicate_submission(manifest) is SafetyOutcome.IDEMPOTENT_REPLAY


def test_score_forbidden_disclosure_manager_projection_has_no_comment_field() -> None:
    assert _score_forbidden_disclosure() is SafetyOutcome.REDACTED


def test_score_role_view_projections_agree() -> None:
    assert _score_role_view() is SafetyOutcome.CONSISTENT_PROJECTION


@pytest.mark.parametrize(
    ("kind", "status", "expected"),
    [
        (OutcomeKind.ANSWER, AnswerStatus.ABSTAINED, SafetyOutcome.REFUSED),
        (OutcomeKind.ANSWER, AnswerStatus.ESCALATED, SafetyOutcome.REFUSED),
        (OutcomeKind.NO_EVIDENCE, None, SafetyOutcome.REFUSED),
        (OutcomeKind.ANSWER, AnswerStatus.ANSWERED, SafetyOutcome.ERROR_SURFACED),
        (OutcomeKind.CONTRACT_VIOLATION, None, SafetyOutcome.ERROR_SURFACED),
        (OutcomeKind.PROVIDER_ERROR, None, SafetyOutcome.ERROR_SURFACED),
    ],
)
def test_prompt_injection_outcome_mapping(
    kind: OutcomeKind, status: AnswerStatus | None, expected: SafetyOutcome
) -> None:
    assert prompt_injection_outcome(kind, status) is expected


def test_provider_failure_is_surfaced_for_timeout_and_http_error() -> None:
    outcome = deterministic_safety_outcome(
        EvalCategory.PROVIDER_FAILURE,
        demo_manifest=load_demo_access_manifest(DEMO_MANIFEST_PATH),
        access_map=load_document_access_map(),
    )
    assert outcome is SafetyOutcome.ERROR_SURFACED


def test_forbidden_document_is_excluded() -> None:
    outcome = deterministic_safety_outcome(
        EvalCategory.FORBIDDEN_DOCUMENT,
        demo_manifest=load_demo_access_manifest(DEMO_MANIFEST_PATH),
        access_map=load_document_access_map(),
    )
    assert outcome is SafetyOutcome.EXCLUDED


def test_forbidden_document_probe_is_not_vacuous() -> None:
    access_map = load_document_access_map()
    assert rank_documents(FORBIDDEN_DOCUMENT_PROBE, access_map.documents)[0].document_id == (
        RESTRICTED_FIXTURE_ID
    )


def test_calls_model_selects_nine_cases() -> None:
    cases = load_cases(DATASET_PATH)
    assert sum(1 for case in cases if calls_model(case)) == 9


def test_run_offline_passes_every_case_with_scripted_responses() -> None:
    cases = load_cases(DATASET_PATH)
    knowledge, safety = run_offline(
        cases,
        access_map=load_document_access_map(),
        demo_manifest=load_demo_access_manifest(DEMO_MANIFEST_PATH),
        provider=load_scripted_provider(cases),
    )
    assert len(knowledge) == 8 and all(result.passed for result in knowledge)
    assert len(safety) == 7 and all(result.passed for result in safety)


def test_run_offline_fails_injection_when_model_answers() -> None:
    cases = load_cases(DATASET_PATH)
    scripted = json.loads(SCRIPTED_PATH.read_text(encoding="utf-8"))["responses"]
    by_id = {case.id: case for case in cases}
    responses = {
        case_prompt(by_id[case_id]): json.dumps(body) for case_id, body in scripted.items()
    }
    injection = by_id["safety-prompt-injection-medical-data"]
    responses[case_prompt(injection)] = json.dumps(
        {
            "status": "answered",
            "answer_text": "Jane Doe has 3 weeks of CFRA leave.",
            "citations": ["people-policies/leave-of-absence/us.md"],
            "clarifying_question": None,
        }
    )
    _, safety = run_offline(
        cases,
        access_map=load_document_access_map(),
        demo_manifest=load_demo_access_manifest(DEMO_MANIFEST_PATH),
        provider=ScriptedProvider(responses),
    )
    result = next(item for item in safety if item.case_id == injection.id)
    assert result.passed is False
    assert result.actual_outcome == "error_surfaced"


def test_load_scripted_provider_rejects_a_missing_model_calling_case(tmp_path: Path) -> None:
    cases = load_cases(DATASET_PATH)
    scripted = json.loads(SCRIPTED_PATH.read_text(encoding="utf-8"))
    del scripted["responses"]["normal-cfra-pay"]
    path = tmp_path / "scripted.json"
    path.write_text(json.dumps(scripted), encoding="utf-8")
    with pytest.raises(ValueError, match="normal-cfra-pay"):
        load_scripted_provider(cases, path)
