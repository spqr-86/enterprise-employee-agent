from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from enterprise_employee_agent.evals.artifact import CostSource, RunStatus
from enterprise_employee_agent.evals.live import (
    COMPARISON_MODEL,
    DECISION_MODEL,
    RunContext,
    main,
    run_live,
)
from enterprise_employee_agent.evals.validator import load_cases
from enterprise_employee_agent.knowledge.access import load_document_access_map
from enterprise_employee_agent.knowledge.answer import OutcomeKind
from enterprise_employee_agent.llm.openrouter import OpenRouterProvider
from enterprise_employee_agent.llm.provider import (
    AnswerRequest,
    ModelConfig,
    ModelPricing,
    ProviderResponse,
    Usage,
)

DATASET_PATH = Path("evals/cases/v0.1.yaml")
ABSTAIN = json.dumps(
    {"status": "abstained", "answer_text": None, "citations": [], "clarifying_question": None}
)
CONTEXT = RunContext(
    run_id="20260913T120000Z",
    started_at=datetime(2026, 9, 13, 12, 0, tzinfo=UTC),
    code_revision="a" * 40,
    code_dirty=False,
    dataset_path="evals/cases/v0.1.yaml",
    dataset_sha256="b" * 64,
)
FAST = ModelConfig(model_id="fast", max_tokens=1000, timeout_seconds=1.0)
SLOW = ModelConfig(model_id="slow", max_tokens=1000, timeout_seconds=1.0)
# Reservation per call = 1000 × $0.001 = $1.00; the input price is 0, so prompt size is irrelevant.
PRICING = {
    model: ModelPricing(
        prompt_usd_per_token=Decimal("0"), completion_usd_per_token=Decimal("0.001")
    )
    for model in ("fast", "slow")
}


class CostingProvider:
    def __init__(self, cost: Decimal | None) -> None:
        self.cost = cost
        self.requests: list[AnswerRequest] = []

    def complete(self, request: AnswerRequest) -> ProviderResponse:
        self.requests.append(request)
        return ProviderResponse(
            content=ABSTAIN,
            usage=Usage(input_tokens=10, output_tokens=5, cost_usd=self.cost),
            raw={"id": f"gen-{len(self.requests)}"},
            provider_model=request.model.model_id,
            latency_seconds=0.5,
        )


def _run(provider, remaining: str, models=(FAST, SLOW)):  # type: ignore[no-untyped-def]
    return run_live(
        cases=load_cases(DATASET_PATH),
        access_map=load_document_access_map(),
        provider=provider,
        models=models,
        pricing=PRICING,
        remaining_budget_usd=Decimal(remaining),
        context=CONTEXT,
    )


def test_models_are_configured_as_the_plan_fixes() -> None:
    assert DECISION_MODEL == ModelConfig(
        model_id="openai/gpt-5-mini",
        max_tokens=4000,
        timeout_seconds=120.0,
        extra_params={"reasoning_effort": "low"},
    )
    assert COMPARISON_MODEL == ModelConfig(
        model_id="deepseek/deepseek-v3.2",
        max_tokens=1500,
        timeout_seconds=120.0,
        extra_params={"temperature": 0},
    )


def test_decision_model_payload_has_no_temperature_and_has_reasoning_effort() -> None:
    # Controller ruling: openai/gpt-5-mini does not accept temperature; reasoning_effort must
    # be present instead. Assert on the actual payload OpenRouterProvider would send.
    provider = OpenRouterProvider("sk-unused", client=httpx.Client())
    request = AnswerRequest(
        model=DECISION_MODEL,
        system_prompt="system",
        user_prompt="user",
        question="question",
        retrieved_ids=(),
    )
    payload = provider.build_payload(request)
    assert "temperature" not in payload
    assert payload["reasoning_effort"] == "low"


def test_all_nine_cases_run_for_decision_model_first_then_comparison() -> None:
    provider = CostingProvider(Decimal("0.01"))
    artifact = _run(provider, "100")
    assert artifact.status is RunStatus.COMPLETE
    assert [call.model_id for call in artifact.calls] == ["fast"] * 9 + ["slow"] * 9
    assert len({call.case_id for call in artifact.calls}) == 9
    assert artifact.total_cost_usd == Decimal("0.18")
    assert artifact.decision_model_id == "fast"
    assert all(call.cost_source is CostSource.PROVIDER for call in artifact.calls)


def test_budget_abort_keeps_completed_records_and_marks_incomplete() -> None:
    # spent after n calls = 0.10 n; call n+1 starts only if 0.10 n + 1.00 <= 1.50, so 6 calls run.
    artifact = _run(CostingProvider(Decimal("0.10")), "1.50")
    assert artifact.status is RunStatus.INCOMPLETE
    assert len(artifact.calls) == 6
    assert artifact.abort_reason is not None and "budget" in artifact.abort_reason


def test_first_call_refused_when_budget_too_small() -> None:
    provider = CostingProvider(Decimal("0.01"))
    artifact = _run(provider, "0.50")
    assert artifact.status is RunStatus.INCOMPLETE
    assert artifact.calls == ()
    assert provider.requests == []


def test_missing_cost_books_the_reservation() -> None:
    artifact = _run(CostingProvider(None), "100", models=(FAST,))
    assert all(call.cost_source is CostSource.RESERVATION for call in artifact.calls)
    assert artifact.total_cost_usd == Decimal("9.000")


def test_provider_error_is_recorded_and_books_reservation() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated", request=request)

    provider = OpenRouterProvider(
        "sk-live-test-secret", client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    artifact = _run(provider, "100", models=(FAST,))
    assert {call.outcome_kind for call in artifact.calls} == {OutcomeKind.PROVIDER_ERROR}
    assert {call.error_kind for call in artifact.calls} == {"timeout"}
    # Controller ruling (D4): a provider error still books the worst-case reservation, since no
    # actual cost was ever reported for that call.
    assert {call.cost_source for call in artifact.calls} == {CostSource.RESERVATION}
    assert artifact.total_cost_usd == Decimal("9.000")
    assert "sk-live-test-secret" not in artifact.model_dump_json()


def test_main_refuses_without_confirmation(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 2
    assert "--confirm-spend" in capsys.readouterr().err


def test_main_refuses_without_api_key(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert main(["--confirm-spend"]) == 2
    assert "OPENROUTER_API_KEY" in capsys.readouterr().err
