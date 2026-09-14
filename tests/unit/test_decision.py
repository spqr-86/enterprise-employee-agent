from __future__ import annotations

import subprocess
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from artifact_factory import make_artifact

from enterprise_employee_agent.evals.artifact import (
    CallRecord,
    CostSource,
    ReviewVerdict,
    RunStatus,
)
from enterprise_employee_agent.evals.decision import (
    ReviewIncomplete,
    Verdict,
    compute_model_metrics,
    decide,
    forbidden_documents_in_context,
    format_baseline_report,
    run_input_mismatches,
    source_changed_since,
)
from enterprise_employee_agent.evals.schema import EvalCategory, KnowledgeEvalCase
from enterprise_employee_agent.evals.scorer import SafetyCaseResult
from enterprise_employee_agent.evals.validator import load_cases
from enterprise_employee_agent.knowledge.access import load_document_access_map
from enterprise_employee_agent.knowledge.answer import OutcomeKind, PromptTemplate

DATASET_PATH = Path("evals/cases/v0.1.yaml")
US = "people-policies/leave-of-absence/us.md"
INDEX = "people-policies/leave-of-absence/_index.md"
MODEL = "openai/gpt-5-mini"


def _call(
    case_id: str,
    *,
    status: str,
    citations: list[str],
    retrieved: list[str],
    kind: OutcomeKind = OutcomeKind.ANSWER,
) -> CallRecord:
    answer = None
    if kind is OutcomeKind.ANSWER:
        answer = {
            "status": status,
            "answer_text": None if status == "abstained" else "text",
            "citations": citations,
            "clarifying_question": None,
        }
    return CallRecord(
        case_id=case_id,
        model_id=MODEL,
        outcome_kind=kind,
        retrieved_ids=tuple(retrieved),
        request=None,
        raw_response=None,
        answer=answer,
        violation_kind=None,
        error_kind=None,
        detail=None,
        provider_model=MODEL,
        input_tokens=100,
        output_tokens=10,
        reserved_usd=Decimal("0.01"),
        cost_usd=Decimal("0.001"),
        cost_source=CostSource.PROVIDER,
        latency_seconds=2.0,
    )


def _good_calls() -> list[CallRecord]:
    calls = []
    for case in load_cases(DATASET_PATH):
        if isinstance(case, KnowledgeEvalCase):
            if case.abstain_expected:
                calls.append(_call(case.id, status="abstained", citations=[], retrieved=[INDEX]))
            else:
                calls.append(_call(case.id, status="answered", citations=[US], retrieved=[US]))
        elif case.category is EvalCategory.PROMPT_INJECTION:
            calls.append(_call(case.id, status="abstained", citations=[], retrieved=[US]))
    return calls


def _reviews(**overrides_by_case: dict[str, object]) -> tuple[ReviewVerdict, ...]:
    reviews = []
    for case in load_cases(DATASET_PATH):
        if isinstance(case, KnowledgeEvalCase):
            fields: dict[str, object] = {
                "case_id": case.id,
                "model_id": MODEL,
                "grounded": None if case.abstain_expected else True,
                "task_success": None if case.abstain_expected else True,
                "reviewer": "Petr",
                "reviewed_on": date(2026, 9, 14),
            }
            fields.update(overrides_by_case.get(case.id, {}))
            reviews.append(ReviewVerdict(**fields))
    return tuple(reviews)


def _safety(passed: bool = True) -> list[SafetyCaseResult]:
    return [
        SafetyCaseResult(
            case_id="s",
            category=EvalCategory.ROLE_VIEW,
            passed=passed,
            actual_outcome="x",
            expected_outcome="x",
        )
    ]


def _metrics(calls=None, reviews=None, require_reviews=True):  # type: ignore[no-untyped-def]
    artifact = make_artifact(
        decision_model_id=MODEL,
        calls=tuple(calls if calls is not None else _good_calls()),
        reviews=reviews if reviews is not None else _reviews(),
    )
    return compute_model_metrics(
        artifact, load_cases(DATASET_PATH), MODEL, require_reviews=require_reviews
    )


def test_all_good_is_keep() -> None:
    metrics = _metrics()
    assert (metrics.groundedness.passed, metrics.groundedness.total) == (7, 7)
    assert (metrics.task_success.passed, metrics.task_success.total) == (7, 7)
    assert (metrics.abstention.passed, metrics.abstention.total) == (1, 1)
    assert (
        decide(
            decision=metrics,
            deterministic_safety=_safety(),
            forbidden_in_context=(),
            run_complete=True,
        )
        is Verdict.KEEP
    )


def test_constant_ranker_control_matches_recall_on_this_corpus() -> None:
    metrics = _metrics()
    assert (metrics.recall_at_1.passed, metrics.recall_at_1.total) == (7, 7)
    assert (
        metrics.constant_ranker_recall_at_1.passed,
        metrics.constant_ranker_recall_at_1.total,
    ) == (7, 7)


def test_deterministic_safety_failure_is_revert() -> None:
    assert (
        decide(
            decision=_metrics(),
            deterministic_safety=_safety(passed=False),
            forbidden_in_context=(),
            run_complete=True,
        )
        is Verdict.REVERT
    )


def test_answered_prompt_injection_is_revert() -> None:
    calls = [
        _call(c.case_id, status="answered", citations=[US], retrieved=[US])
        if c.case_id == "safety-prompt-injection-medical-data"
        else c
        for c in _good_calls()
    ]
    metrics = _metrics(calls=calls)
    assert metrics.prompt_injection is not None and metrics.prompt_injection.passed is False
    assert (
        decide(
            decision=metrics,
            deterministic_safety=_safety(),
            forbidden_in_context=(),
            run_complete=True,
        )
        is Verdict.REVERT
    )


def test_forbidden_document_in_context_is_revert() -> None:
    calls = _good_calls()
    calls[0] = _call(
        calls[0].case_id,
        status="answered",
        citations=[US],
        retrieved=[US, "synthetic/hr-only-note"],
    )
    artifact = make_artifact(decision_model_id=MODEL, calls=tuple(calls))
    leaked = forbidden_documents_in_context(artifact, load_document_access_map())
    assert leaked == (calls[0].case_id,)
    assert (
        decide(
            decision=_metrics(),
            deterministic_safety=_safety(),
            forbidden_in_context=leaked,
            run_complete=True,
        )
        is Verdict.REVERT
    )


def test_one_ungrounded_review_is_investigate() -> None:
    metrics = _metrics(reviews=_reviews(**{"normal-cfra-pay": {"grounded": False}}))
    assert metrics.groundedness.passed == 6
    assert (
        decide(
            decision=metrics,
            deterministic_safety=_safety(),
            forbidden_in_context=(),
            run_complete=True,
        )
        is Verdict.INVESTIGATE
    )


def test_contract_violation_fails_groundedness_even_if_review_says_grounded() -> None:
    calls = [
        _call(
            c.case_id, status="", citations=[], retrieved=[US], kind=OutcomeKind.CONTRACT_VIOLATION
        )
        if c.case_id == "normal-cfra-pay"
        else c
        for c in _good_calls()
    ]
    metrics = _metrics(calls=calls)
    assert metrics.groundedness.passed == 6
    assert metrics.task_success.passed == 6
    assert any(row.case_id == "normal-cfra-pay" for row in metrics.failures)


def test_failed_abstention_is_investigate() -> None:
    calls = [
        _call(c.case_id, status="answered", citations=[INDEX], retrieved=[INDEX])
        if c.case_id == "out-of-scope-germany"
        else c
        for c in _good_calls()
    ]
    metrics = _metrics(calls=calls)
    assert metrics.abstention.passed == 0
    assert (
        decide(
            decision=metrics,
            deterministic_safety=_safety(),
            forbidden_in_context=(),
            run_complete=True,
        )
        is Verdict.INVESTIGATE
    )


def test_incomplete_run_is_investigate() -> None:
    # Controller ruling C2/D2: use the full metrics (all calls, all reviews — the same inputs
    # that give KEEP with run_complete=True in test_all_good_is_keep) with run_complete=False,
    # so this asserts INVESTIGATE is driven by run_complete, not by an incomplete calls slice.
    metrics = _metrics()
    assert (
        decide(
            decision=metrics,
            deterministic_safety=_safety(),
            forbidden_in_context=(),
            run_complete=False,
        )
        is Verdict.INVESTIGATE
    )


def test_missing_review_raises_for_decision_model() -> None:
    with pytest.raises(ReviewIncomplete) as excinfo:
        _metrics(reviews=_reviews()[1:])
    assert excinfo.value.missing == (_reviews()[0].case_id,)


def test_report_states_control_verdict_next_action_and_deviation() -> None:
    metrics = _metrics()
    artifact = make_artifact(
        decision_model_id=MODEL,
        calls=tuple(_good_calls()),
        reviews=_reviews(),
        status=RunStatus.COMPLETE,
    )
    text = format_baseline_report(
        artifact=artifact,
        metrics=[metrics],
        deterministic_safety=_safety(),
        forbidden_in_context=(),
        verdict=Verdict.KEEP,
        next_action="Do the next thing.",
    )
    assert "not decision-bearing" in text
    assert "7/7 (100%)" in text
    assert "Verdict: **KEEP**" in text
    assert "Do the next thing." in text
    assert "discriminate between documents" in text
    assert "DEVELOPMENT_FRAMEWORK.md §10" in text
    assert "decision 0004" in text
    # Controller ruling C3: per-call operating data must be reported per case, not only per
    # model. Every case ID from the run appears as a row in that table.
    assert "## Per-call operating data" in text
    assert "| normal-cfra-pay |" in text


def test_comparison_model_without_reviews_is_not_reviewed_not_zero() -> None:
    calls = [
        _call(
            c.case_id, status="", citations=[], retrieved=[US], kind=OutcomeKind.CONTRACT_VIOLATION
        )
        if c.case_id == "normal-cfra-pay"
        else c
        for c in _good_calls()
    ]
    metrics = _metrics(calls=calls, reviews=(), require_reviews=False)
    assert metrics.groundedness is None and metrics.task_success is None
    assert (metrics.abstention.passed, metrics.abstention.total) == (1, 1)
    assert [(row.case_id, row.metric) for row in metrics.failures] == [
        ("normal-cfra-pay", "recall"),
        ("normal-cfra-pay", "answer_contract"),
    ]
    artifact = make_artifact(
        decision_model_id="other/decision-model", calls=tuple(calls), status=RunStatus.COMPLETE
    )
    text = format_baseline_report(
        artifact=artifact,
        metrics=[metrics],
        deterministic_safety=_safety(),
        forbidden_in_context=(),
        verdict=Verdict.INVESTIGATE,
        next_action="n",
    )
    assert "| Groundedness | not reviewed |" in text
    assert "| Task success | not reviewed |" in text
    assert "0/7" not in text


def test_partial_reviews_raise_for_comparison_model_too() -> None:
    with pytest.raises(ReviewIncomplete):
        _metrics(reviews=_reviews()[1:], require_reviews=False)


def test_run_input_mismatches_names_each_changed_input() -> None:
    access_map = load_document_access_map()
    prompt = PromptTemplate(version="answer-v1", system="s", user="u")
    artifact = make_artifact(
        prompt_sha256=prompt.sha256,
        access_version=access_map.access_version,
        corpus_version=access_map.corpus_version,
    )
    assert (
        run_input_mismatches(
            artifact, dataset_sha256=artifact.dataset_sha256, prompt=prompt, access_map=access_map
        )
        == ()
    )
    changed = run_input_mismatches(
        artifact,
        dataset_sha256="d" * 64,
        prompt=PromptTemplate(version="answer-v2", system="s2", user="u"),
        access_map=access_map,
    )
    assert [item.split(":")[0] for item in changed] == [
        "dataset_sha256",
        "prompt_version",
        "prompt_sha256",
    ]


def test_source_changed_since_sees_uncommitted_untracked_and_committed_changes(
    tmp_path: Path,
) -> None:
    def git(*args: str) -> str:
        return subprocess.run(
            [
                "git",
                "-c",
                "user.name=t",
                "-c",
                "user.email=t@example.invalid",
                "-c",
                "commit.gpgsign=false",
                *args,
            ],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    git("init", "-q")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-q", "-m", "run")
    revision = git("rev-parse", "HEAD")
    assert source_changed_since(revision, repo_root=tmp_path) is False

    (tmp_path / "evals" / "cases").mkdir(parents=True)
    (tmp_path / "evals" / "cases" / "new.yaml").write_text("[]\n", encoding="utf-8")
    assert source_changed_since(revision, repo_root=tmp_path) is True  # untracked
    (tmp_path / "evals" / "cases" / "new.yaml").unlink()

    (tmp_path / "src" / "a.py").write_text("x = 2\n", encoding="utf-8")
    assert source_changed_since(revision, repo_root=tmp_path) is True  # uncommitted
    git("commit", "-q", "-am", "later")
    assert source_changed_since(revision, repo_root=tmp_path) is True  # committed
