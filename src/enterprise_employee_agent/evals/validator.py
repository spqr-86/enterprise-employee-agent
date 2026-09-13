"""Dataset-level validation for the micro-eval case list, run before scoring."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path

import yaml
from pydantic import TypeAdapter

from enterprise_employee_agent.evals.schema import EvalCase, KnowledgeEvalCase

_CASES_ADAPTER = TypeAdapter(list[EvalCase])


class DatasetValidationError(Exception):
    """Raised with every problem found in a case dataset, listed together."""

    def __init__(self, issues: Sequence[str]) -> None:
        self.issues = tuple(issues)
        super().__init__("; ".join(self.issues))


def load_cases(path: Path) -> list[EvalCase]:
    """Read and parse a YAML dataset file into typed cases."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise DatasetValidationError([f"{path}: dataset must be a YAML list of cases"])
    return _CASES_ADAPTER.validate_python(raw)


def validate_dataset(cases: Iterable[EvalCase], known_document_ids: frozenset[str]) -> None:
    """Raise DatasetValidationError listing every cross-case problem found."""
    case_list = list(cases)
    issues: list[str] = []

    seen_ids: set[str] = set()
    for case in case_list:
        if case.id in seen_ids:
            issues.append(f"duplicate case id: {case.id}")
        seen_ids.add(case.id)

    for case in case_list:
        if isinstance(case, KnowledgeEvalCase):
            for document_id in case.expected_evidence:
                if document_id not in known_document_ids:
                    issues.append(
                        f"case {case.id}: expected_evidence references unknown document "
                        f"id {document_id!r}"
                    )

    if issues:
        raise DatasetValidationError(issues)
