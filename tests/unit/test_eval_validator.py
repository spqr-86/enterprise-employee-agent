from __future__ import annotations

from pathlib import Path

import pytest

from enterprise_employee_agent.evals.schema import (
    EvalCategory,
    KnowledgeEvalCase,
    SafetyEvalCase,
    SafetyOutcome,
)
from enterprise_employee_agent.evals.validator import (
    DatasetValidationError,
    load_cases,
    validate_dataset,
)


def _knowledge_case(case_id: str, evidence: tuple[str, ...]) -> KnowledgeEvalCase:
    return KnowledgeEvalCase(
        id=case_id,
        category=EvalCategory.NORMAL,
        question="q",
        expected="e",
        expected_evidence=evidence,
    )


def _safety_case(case_id: str) -> SafetyEvalCase:
    return SafetyEvalCase(
        id=case_id,
        category=EvalCategory.STALE_CONFIRMATION,
        scenario="s",
        expected="e",
        expected_outcome=SafetyOutcome.REJECTED_STALE,
    )


def test_validate_dataset_passes_for_valid_cases() -> None:
    cases = [_knowledge_case("k1", ("doc-a",)), _safety_case("s1")]
    validate_dataset(cases, known_document_ids=frozenset({"doc-a"}))


def test_validate_dataset_rejects_duplicate_ids() -> None:
    cases = [_knowledge_case("k1", ("doc-a",)), _knowledge_case("k1", ("doc-a",))]
    with pytest.raises(DatasetValidationError) as excinfo:
        validate_dataset(cases, known_document_ids=frozenset({"doc-a"}))
    assert any("duplicate case id: k1" in issue for issue in excinfo.value.issues)


def test_validate_dataset_rejects_unknown_evidence_document() -> None:
    cases = [_knowledge_case("k1", ("missing-doc",))]
    with pytest.raises(DatasetValidationError) as excinfo:
        validate_dataset(cases, known_document_ids=frozenset({"doc-a"}))
    assert any("missing-doc" in issue for issue in excinfo.value.issues)


def test_validate_dataset_reports_every_issue_together() -> None:
    cases = [
        _knowledge_case("k1", ("missing-doc",)),
        _knowledge_case("k1", ("doc-a",)),
    ]
    with pytest.raises(DatasetValidationError) as excinfo:
        validate_dataset(cases, known_document_ids=frozenset({"doc-a"}))
    assert len(excinfo.value.issues) == 2


def test_load_cases_parses_yaml_file(tmp_path: Path) -> None:
    dataset = tmp_path / "cases.yaml"
    dataset.write_text(
        "- id: k1\n"
        "  category: normal\n"
        "  question: q\n"
        "  expected: e\n"
        "  expected_evidence: [doc-a]\n",
        encoding="utf-8",
    )
    cases = load_cases(dataset)
    assert len(cases) == 1
    assert cases[0].id == "k1"


def test_load_cases_rejects_non_list_yaml(tmp_path: Path) -> None:
    dataset = tmp_path / "cases.yaml"
    dataset.write_text("id: not-a-list\n", encoding="utf-8")
    with pytest.raises(DatasetValidationError):
        load_cases(dataset)
