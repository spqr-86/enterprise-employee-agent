from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from enterprise_employee_agent.evals.artifact import (
    CostSource,
    ModelRunConfig,
    RunArtifact,
    RunStatus,
    call_record_from_outcome,
)
from enterprise_employee_agent.knowledge.answer import OutcomeKind, PipelineOutcome
from enterprise_employee_agent.llm.contract import AnswerContract, AnswerStatus
from enterprise_employee_agent.llm.provider import ProviderResponse, Usage

US = "people-policies/leave-of-absence/us.md"


def make_outcome() -> PipelineOutcome:
    return PipelineOutcome(
        kind=OutcomeKind.ANSWER,
        retrieved_ids=(US,),
        request_record={
            "question": "q",
            "retrieved_ids": [US],
            "model_id": "m",
            "max_tokens": 10,
            "timeout_seconds": 1.0,
            "params": {},
        },
        response=ProviderResponse(
            content="{}",
            usage=Usage(input_tokens=100, output_tokens=20, cost_usd=Decimal("0.000123")),
            raw={"id": "gen-1"},
            provider_model="m-2026",
            latency_seconds=1.5,
        ),
        answer=AnswerContract(
            status=AnswerStatus.ANSWERED, answer_text="a", citations=(US,), clarifying_question=None
        ),
    )


def make_artifact(**overrides: object) -> RunArtifact:
    record = call_record_from_outcome(
        "k1",
        "m",
        make_outcome(),
        reserved_usd=Decimal("0.01"),
        cost_usd=Decimal("0.000123"),
        cost_source=CostSource.PROVIDER,
    )
    fields: dict[str, object] = {
        "run_id": "20260913T120000Z",
        "started_at": datetime(2026, 9, 13, 12, 0, tzinfo=UTC),
        "code_revision": "a" * 40,
        "code_dirty": False,
        "corpus_version": "us-leave-2026-09-12",
        "access_version": "document-access-v1",
        "dataset_path": "evals/cases/v0.1.yaml",
        "dataset_sha256": "b" * 64,
        "prompt_version": "answer-v1",
        "prompt_sha256": "c" * 64,
        "retrieval_version": "lexical-overlap-v1",
        "k": 1,
        "eval_role": "employee",
        "decision_model_id": "m",
        "models": (
            ModelRunConfig(
                model_id="m",
                max_tokens=10,
                timeout_seconds=1.0,
                params={},
                prompt_usd_per_token=Decimal("0.00000025"),
                completion_usd_per_token=Decimal("0.000002"),
            ),
        ),
        "budget_total_usd": Decimal("0.50"),
        "budget_remaining_at_start_usd": Decimal("0.50"),
        "status": RunStatus.COMPLETE,
        "calls": (record,),
    }
    fields.update(overrides)
    return RunArtifact(**fields)
