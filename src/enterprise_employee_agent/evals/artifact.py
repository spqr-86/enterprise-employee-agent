"""Issue #8 live run artifact: evidence of what happened, never a test fixture.

Written once to ``experiments/issue-8/<run_id>.json``. Afterwards only manual review verdicts are
appended. Requests are stored through ``AnswerRequest.record()``, which carries no keys, headers or
transport fields.
"""

# ANCHOR: The Issue #8 live run artifact. write_new_artifact() is the only way a run is recorded
# (refuses to overwrite); load_run_artifact() and append_reviews() are the only ways it is read
# back or modified afterward — append_reviews() rejects duplicate or unknown (case_id, model_id)
# verdicts and rewrites nothing but the reviews tuple. call_record_from_outcome() maps a Task 5
# PipelineOutcome onto a CallRecord: response.raw is already the allowlisted subset a concrete
# provider (llm/openrouter.py) chose to keep, so this module does not re-filter it. Task 9
# (budget) sums total_cost_usd across artifacts on disk; Task 10 (live CLI) is the only writer;
# Task 11 (decision/report) and Task 13 (manual review) are the only readers.

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import AwareDatetime, Field, TypeAdapter

from enterprise_employee_agent.knowledge.answer import OutcomeKind, PipelineOutcome
from enterprise_employee_agent.leave.contracts import ContractModel


class RunStatus(StrEnum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"


class CostSource(StrEnum):
    PROVIDER = "provider"
    RESERVATION = "reservation"
    NONE = "none"


class CallRecord(ContractModel):
    case_id: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    outcome_kind: OutcomeKind
    retrieved_ids: tuple[str, ...]
    request: dict[str, Any] | None
    raw_response: dict[str, Any] | None
    answer: dict[str, Any] | None
    violation_kind: str | None
    error_kind: str | None
    detail: str | None
    provider_model: str | None
    input_tokens: int | None
    output_tokens: int | None
    reserved_usd: Decimal | None
    cost_usd: Decimal
    cost_source: CostSource
    latency_seconds: float | None
    # HTTP status of a provider error; None for successes and non-HTTP failures.
    status_code: int | None = None


class ModelRunConfig(ContractModel):
    model_id: str
    max_tokens: int
    timeout_seconds: float
    params: dict[str, Any]
    prompt_usd_per_token: Decimal
    completion_usd_per_token: Decimal


class ReviewVerdict(ContractModel):
    case_id: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    grounded: bool | None
    task_success: bool | None
    reviewer: str = Field(min_length=1)
    reviewed_on: date
    notes: str = ""


class RunArtifact(ContractModel):
    schema_version: Literal[1] = 1
    issue: Literal[8] = 8
    run_id: str = Field(pattern=r"^[0-9]{8}T[0-9]{6}Z$")
    started_at: AwareDatetime
    code_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    code_dirty: bool
    corpus_version: str
    access_version: str
    dataset_path: str
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    prompt_version: str
    prompt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    retrieval_version: str
    k: int = Field(ge=1)
    eval_role: str
    decision_model_id: str
    models: tuple[ModelRunConfig, ...]
    budget_total_usd: Decimal
    budget_remaining_at_start_usd: Decimal
    status: RunStatus
    abort_reason: str | None = None
    calls: tuple[CallRecord, ...]
    reviews: tuple[ReviewVerdict, ...] = ()

    @property
    def total_cost_usd(self) -> Decimal:
        return sum((call.cost_usd for call in self.calls), Decimal("0"))


def call_record_from_outcome(
    case_id: str,
    model_id: str,
    outcome: PipelineOutcome,
    *,
    reserved_usd: Decimal | None,
    cost_usd: Decimal,
    cost_source: CostSource,
) -> CallRecord:
    response = outcome.response
    return CallRecord(
        case_id=case_id,
        model_id=model_id,
        outcome_kind=outcome.kind,
        retrieved_ids=outcome.retrieved_ids,
        request=dict(outcome.request_record) if outcome.request_record is not None else None,
        raw_response=dict(response.raw) if response is not None else None,
        answer=outcome.answer.model_dump(mode="json") if outcome.answer is not None else None,
        violation_kind=outcome.violation_kind.value if outcome.violation_kind else None,
        error_kind=outcome.error_kind.value if outcome.error_kind else None,
        detail=outcome.detail,
        provider_model=response.provider_model if response is not None else None,
        input_tokens=response.usage.input_tokens if response is not None else None,
        output_tokens=response.usage.output_tokens if response is not None else None,
        reserved_usd=reserved_usd,
        cost_usd=cost_usd,
        cost_source=cost_source,
        latency_seconds=response.latency_seconds if response is not None else None,
        status_code=outcome.status_code,
    )


def write_new_artifact(artifact: RunArtifact, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{artifact.run_id}.json"
    with path.open("x", encoding="utf-8") as handle:
        handle.write(artifact.model_dump_json(indent=2) + "\n")
    return path


def load_run_artifact(path: Path) -> RunArtifact:
    return RunArtifact.model_validate_json(path.read_text(encoding="utf-8"))


def append_reviews(path: Path, verdicts: Sequence[ReviewVerdict]) -> RunArtifact:
    artifact = load_run_artifact(path)
    called = {(call.case_id, call.model_id) for call in artifact.calls}
    reviewed = {(review.case_id, review.model_id) for review in artifact.reviews}
    for verdict in verdicts:
        key = (verdict.case_id, verdict.model_id)
        if key not in called:
            raise ValueError(f"no call recorded for {key}")
        if key in reviewed:
            raise ValueError(f"already reviewed: {key}")
        reviewed.add(key)
    updated = RunArtifact.model_validate(
        artifact.model_dump(mode="python") | {"reviews": (*artifact.reviews, *verdicts)}
    )
    path.write_text(updated.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return updated


_VERDICTS_ADAPTER = TypeAdapter(list[ReviewVerdict])


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Issue #8 run artifact tools.")
    commands = parser.add_subparsers(dest="command", required=True)
    review = commands.add_parser("review", help="append manual review verdicts from YAML")
    review.add_argument("artifact", type=Path)
    review.add_argument("verdicts", type=Path)
    args = parser.parse_args(argv)

    raw = yaml.safe_load(args.verdicts.read_text(encoding="utf-8"))
    try:
        updated = append_reviews(args.artifact, _VERDICTS_ADAPTER.validate_python(raw))
    except ValueError as error:
        print(f"review not appended: {error}", file=sys.stderr)
        return 1
    print(f"{len(updated.reviews)} review verdicts in {args.artifact}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
