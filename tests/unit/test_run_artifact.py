from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from artifact_factory import US, make_artifact

from enterprise_employee_agent.evals.artifact import (
    ReviewVerdict,
    RunArtifact,
    append_reviews,
    load_run_artifact,
    main,
    write_new_artifact,
)
from enterprise_employee_agent.knowledge.answer import OutcomeKind


def test_call_record_maps_outcome_fields() -> None:
    record = make_artifact().calls[0]
    assert record.outcome_kind is OutcomeKind.ANSWER
    assert record.answer == {
        "status": "answered",
        "answer_text": "a",
        "citations": [US],
        "clarifying_question": None,
    }
    assert record.input_tokens == 100 and record.output_tokens == 20
    assert record.provider_model == "m-2026"
    assert record.raw_response == {"id": "gen-1"}


def test_artifact_round_trips_with_exact_decimals(tmp_path: Path) -> None:
    path = write_new_artifact(make_artifact(), tmp_path)
    assert path == tmp_path / "20260913T120000Z.json"
    loaded = load_run_artifact(path)
    assert loaded == make_artifact()
    assert loaded.total_cost_usd == Decimal("0.000123")


def test_write_refuses_to_overwrite(tmp_path: Path) -> None:
    write_new_artifact(make_artifact(), tmp_path)
    with pytest.raises(FileExistsError):
        write_new_artifact(make_artifact(), tmp_path)


def _verdict(**overrides: object) -> ReviewVerdict:
    fields: dict[str, object] = {
        "case_id": "k1",
        "model_id": "m",
        "grounded": True,
        "task_success": False,
        "reviewer": "Petr",
        "reviewed_on": date(2026, 9, 14),
        "notes": "misses the offset",
    }
    fields.update(overrides)
    return ReviewVerdict(**fields)


def test_append_reviews_changes_only_reviews(tmp_path: Path) -> None:
    path = write_new_artifact(make_artifact(), tmp_path)
    updated = append_reviews(path, [_verdict()])
    assert updated.reviews == (_verdict(),)
    assert updated.model_copy(update={"reviews": ()}) == make_artifact()
    assert load_run_artifact(path) == updated


def test_append_reviews_rejects_duplicates_and_unknown_calls(tmp_path: Path) -> None:
    path = write_new_artifact(make_artifact(), tmp_path)
    append_reviews(path, [_verdict()])
    with pytest.raises(ValueError, match="already reviewed"):
        append_reviews(path, [_verdict()])
    with pytest.raises(ValueError, match="no call"):
        append_reviews(path, [_verdict(case_id="unknown")])


def test_review_cli_reads_yaml(tmp_path: Path) -> None:
    path = write_new_artifact(make_artifact(), tmp_path)
    verdicts = tmp_path / "review.yaml"
    verdicts.write_text(
        "- case_id: k1\n  model_id: m\n  grounded: true\n  task_success: true\n"
        "  reviewer: Petr\n  reviewed_on: 2026-09-14\n",
        encoding="utf-8",
    )
    assert main(["review", str(path), str(verdicts)]) == 0
    assert load_run_artifact(path).reviews[0].task_success is True


def test_artifact_rejects_other_issue_numbers() -> None:
    with pytest.raises(ValueError):
        RunArtifact.model_validate(json.loads(make_artifact().model_dump_json()) | {"issue": 9})
