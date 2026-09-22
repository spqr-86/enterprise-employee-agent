from __future__ import annotations

from pathlib import Path

from enterprise_employee_agent.evals.schema import KNOWLEDGE_CATEGORIES, SAFETY_CATEGORIES
from enterprise_employee_agent.evals.validator import load_cases, validate_dataset
from enterprise_employee_agent.knowledge.corpus import load_manifest

DATASET_PATH = Path("evals/cases/v0.1.yaml")


def test_v0_1_dataset_loads_and_validates_against_the_real_manifest() -> None:
    manifest = load_manifest()
    document_ids = frozenset(document.id for document in manifest.documents)
    cases = load_cases(DATASET_PATH)
    validate_dataset(cases, document_ids)


def test_v0_1_dataset_has_sixteen_cases() -> None:
    assert len(load_cases(DATASET_PATH)) == 16


def test_v0_1_dataset_has_the_forbidden_document_case() -> None:
    cases = {case.id: case for case in load_cases(DATASET_PATH)}
    case = cases["safety-forbidden-document-retrieval"]
    assert case.category.value == "forbidden_document"
    assert case.expected_outcome.value == "excluded"  # type: ignore[union-attr]


def test_v0_1_dataset_covers_every_category_at_least_once() -> None:
    cases = load_cases(DATASET_PATH)
    seen = {case.category for case in cases}
    assert seen == KNOWLEDGE_CATEGORIES | SAFETY_CATEGORIES


def test_v0_1_dataset_has_unique_ids() -> None:
    cases = load_cases(DATASET_PATH)
    ids = [case.id for case in cases]
    assert len(ids) == len(set(ids))
