from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from artifact_factory import make_artifact

from enterprise_employee_agent.evals import live
from enterprise_employee_agent.evals.artifact import (
    CostSource,
    RunArtifact,
    RunStatus,
    load_run_artifact,
    write_new_artifact,
)
from enterprise_employee_agent.evals.budget import ISSUE_8_BUDGET_USD
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
        extra_params={"reasoning": {"effort": "low"}},
    )
    assert COMPARISON_MODEL == ModelConfig(
        model_id="deepseek/deepseek-v3.2",
        max_tokens=1500,
        timeout_seconds=120.0,
        extra_params={"temperature": 0},
    )


def test_decision_model_payload_has_no_temperature_and_uses_reasoning_object() -> None:
    # Controller ruling: openai/gpt-5-mini does not accept temperature; OpenRouter's documented
    # reasoning object must be present instead. Assert on the actual payload OpenRouterProvider
    # would send.
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
    assert "reasoning_effort" not in payload
    assert payload["reasoning"] == {"effort": "low"}


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
    # Final review C1: two consecutive provider errors on one model stop the run.
    assert len(artifact.calls) == 2
    assert artifact.total_cost_usd == Decimal("2.000")
    assert "sk-live-test-secret" not in artifact.model_dump_json()


def _http_provider(statuses: list[int], seen: list[httpx.Request]) -> OpenRouterProvider:
    """Serves the given HTTP statuses in order, then valid abstentions."""

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        index = len(seen) - 1
        if index < len(statuses):
            return httpx.Response(
                statuses[index], json={"error": {"message": f"rejected #{index + 1}"}}
            )
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": ABSTAIN}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.01},
            },
        )

    return OpenRouterProvider(
        "sk-live-test-secret", client=httpx.Client(transport=httpx.MockTransport(handler))
    )


@pytest.mark.parametrize("status_code", [400, 401, 402, 403, 404])
def test_rejected_request_configuration_stops_the_run_after_one_call(status_code: int) -> None:
    seen: list[httpx.Request] = []
    artifact = _run(_http_provider([status_code], seen), "100")
    assert len(seen) == 1
    assert artifact.status is RunStatus.INCOMPLETE
    assert len(artifact.calls) == 1
    call = artifact.calls[0]
    assert call.status_code == status_code
    assert call.detail == f"provider returned HTTP {status_code}: rejected #1"
    assert artifact.abort_reason is not None
    assert f"HTTP {status_code}" in artifact.abort_reason
    assert call.case_id in artifact.abort_reason and "fast" in artifact.abort_reason


def test_two_consecutive_server_errors_on_one_model_stop_the_run() -> None:
    seen: list[httpx.Request] = []
    artifact = _run(_http_provider([503, 500], seen), "100")
    assert len(seen) == 2
    assert artifact.status is RunStatus.INCOMPLETE
    assert [call.status_code for call in artifact.calls] == [503, 500]
    assert artifact.abort_reason is not None and "consecutive" in artifact.abort_reason


def test_single_server_error_followed_by_success_does_not_stop_the_run() -> None:
    seen: list[httpx.Request] = []
    artifact = _run(_http_provider([503], seen), "100")
    assert artifact.status is RunStatus.COMPLETE
    assert len(artifact.calls) == 18
    assert artifact.calls[0].status_code == 503
    assert artifact.calls[1].status_code is None


def test_non_consecutive_errors_do_not_stop_the_run() -> None:
    seen: list[httpx.Request] = []
    # 503, success, 429 on the same model: never two in a row.
    statuses = [503, 200, 429]

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        index = len(seen) - 1
        if index < len(statuses) and statuses[index] != 200:
            return httpx.Response(statuses[index], json={"error": {"message": "busy"}})
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": ABSTAIN}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.01},
            },
        )

    provider = OpenRouterProvider(
        "sk-test", client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    artifact = _run(provider, "100")
    assert artifact.status is RunStatus.COMPLETE
    assert len(artifact.calls) == 18


def test_main_refuses_without_confirmation(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 2
    assert "--confirm-spend" in capsys.readouterr().err


def test_main_refuses_without_api_key(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert main(["--confirm-spend"]) == 2
    assert "OPENROUTER_API_KEY" in capsys.readouterr().err


def test_main_refuses_on_dirty_tree_before_creating_a_client(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    monkeypatch.setattr(
        live, "_git", lambda *args: " M some/file.py" if args[0] == "status" else "f" * 40
    )

    def _forbidden_client(*args: object, **kwargs: object) -> None:
        raise AssertionError("httpx.Client must not be constructed on a dirty-tree refusal")

    monkeypatch.setattr(live.httpx, "Client", _forbidden_client)

    assert main(["--confirm-spend"]) == 2
    assert "dirty" in capsys.readouterr().err


def _supported(model: ModelConfig) -> list[str]:
    return ["max_tokens", "response_format", "structured_outputs", *model.extra_params]


def _models_body(overrides: dict[str, list[str]] | None = None) -> dict[str, object]:
    overrides = overrides or {}
    return {
        "data": [
            {
                "id": model.model_id,
                "pricing": {"prompt": "0", "completion": "1"},
                "supported_parameters": overrides.get(model.model_id, _supported(model)),
            }
            for model in live.LIVE_MODELS
        ]
    }


def _patch_main_offline(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    models_body: dict[str, object],
    chat_requests: list[httpx.Request],
) -> None:
    """Preflight passes; the only HTTP traffic goes to a MockTransport."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    monkeypatch.setattr(live, "_git", lambda *args: "" if args[0] == "status" else "f" * 40)
    monkeypatch.setattr(live, "EXPERIMENTS_DIR", tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json=models_body)
        chat_requests.append(request)
        return httpx.Response(500, json={"error": {"message": "must not be called"}})

    real_client = httpx.Client
    monkeypatch.setattr(
        live.httpx, "Client", lambda: real_client(transport=httpx.MockTransport(handler))
    )


def test_main_returns_incomplete_on_budget_refusal_of_first_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    chat: list[httpx.Request] = []
    _patch_main_offline(monkeypatch, tmp_path, _models_body(), chat)
    assert main(["--confirm-spend"]) == 3
    assert chat == []


@pytest.mark.parametrize(
    ("model", "missing"),
    [
        (DECISION_MODEL, "structured_outputs"),
        (DECISION_MODEL, "reasoning"),
        (COMPARISON_MODEL, "temperature"),
        (COMPARISON_MODEL, "response_format"),
        (COMPARISON_MODEL, "max_tokens"),
    ],
)
def test_main_refuses_before_spend_when_a_model_lacks_a_required_parameter(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    model: ModelConfig,
    missing: str,
) -> None:
    supported = [name for name in _supported(model) if name != missing]
    chat: list[httpx.Request] = []
    _patch_main_offline(monkeypatch, tmp_path, _models_body({model.model_id: supported}), chat)
    assert main(["--confirm-spend", "--output-dir", str(tmp_path)]) == 2
    assert chat == []
    assert list(tmp_path.glob("*.json")) == []
    err = capsys.readouterr().err
    assert model.model_id in err and missing in err


def test_budget_counts_experiments_dir_even_when_output_dir_differs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # IMPORTANT ruling 1: --output-dir must not grant a fresh budget by reading spend from
    # somewhere other than EXPERIMENTS_DIR.
    experiments_dir = tmp_path / "experiments"
    other_dir = tmp_path / "elsewhere"
    monkeypatch.setattr(live, "EXPERIMENTS_DIR", experiments_dir)
    spent_artifact = make_artifact()
    write_new_artifact(spent_artifact, experiments_dir)

    remaining = live._remaining_budget(other_dir)

    assert remaining == ISSUE_8_BUDGET_USD - spent_artifact.total_cost_usd


def test_budget_does_not_double_count_when_output_dir_is_experiments_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    experiments_dir = tmp_path / "experiments"
    monkeypatch.setattr(live, "EXPERIMENTS_DIR", experiments_dir)
    spent_artifact = make_artifact()
    write_new_artifact(spent_artifact, experiments_dir)

    remaining = live._remaining_budget(experiments_dir)

    assert remaining == ISSUE_8_BUDGET_USD - spent_artifact.total_cost_usd


def test_negative_cost_is_treated_as_absent_and_books_reservation() -> None:
    # IMPORTANT ruling 2: a negative reported cost must not be trusted (it would free budget).
    artifact = _run(CostingProvider(Decimal("-1")), "100", models=(FAST,))
    assert all(call.cost_source is CostSource.RESERVATION for call in artifact.calls)
    assert artifact.total_cost_usd == Decimal("9.000")


def test_nan_cost_is_treated_as_absent_and_books_reservation() -> None:
    # IMPORTANT ruling 2: a non-finite reported cost must not crash the run.
    artifact = _run(CostingProvider(Decimal("NaN")), "100", models=(FAST,))
    assert all(call.cost_source is CostSource.RESERVATION for call in artifact.calls)
    assert artifact.total_cost_usd == Decimal("9.000")


class CrashingProvider:
    """Answers normally until ``crash_at``, then raises instead of returning a response."""

    def __init__(
        self, cost: Decimal, *, crash_at: int, exc_factory: type[BaseException] = RuntimeError
    ) -> None:
        self.cost = cost
        self.crash_at = crash_at
        self.exc_factory = exc_factory
        self.calls = 0

    def complete(self, request: AnswerRequest) -> ProviderResponse:
        self.calls += 1
        if self.calls == self.crash_at:
            raise self.exc_factory("simulated crash")
        return ProviderResponse(
            content=ABSTAIN,
            usage=Usage(input_tokens=10, output_tokens=5, cost_usd=self.cost),
            raw={"id": f"gen-{self.calls}"},
            provider_model=request.model.model_id,
            latency_seconds=0.1,
        )


def test_runtime_error_mid_run_books_reservation_and_still_yields_an_artifact() -> None:
    # CRITICAL ruling: a crash after paid calls must not make that spend invisible.
    provider = CrashingProvider(Decimal("0.01"), crash_at=3)
    with pytest.raises(RuntimeError) as exc_info:
        _run(provider, "100", models=(FAST,))
    artifact = exc_info.value.live_run_artifact  # type: ignore[attr-defined]
    assert artifact.status is RunStatus.INCOMPLETE
    assert len(artifact.calls) == 3
    assert artifact.calls[-1].cost_source is CostSource.RESERVATION
    assert artifact.total_cost_usd >= Decimal("0.01") * 2 + Decimal("1.00")


def test_call_record_build_failure_still_books_the_paid_call_as_a_reservation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Review must-fix (Task 10 follow-up): a paid call must never disappear from the artifact
    # just because call_record_from_outcome() itself raised (e.g. a pydantic validation error)
    # after the ledger already settled that call's cost.
    original_call_record_from_outcome = live.call_record_from_outcome
    calls_made = {"n": 0}

    def flaky_call_record_from_outcome(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        calls_made["n"] += 1
        if calls_made["n"] == 2:
            raise ValueError("simulated call-record construction failure")
        return original_call_record_from_outcome(*args, **kwargs)

    monkeypatch.setattr(live, "call_record_from_outcome", flaky_call_record_from_outcome)

    provider = CostingProvider(Decimal("0.01"))
    with pytest.raises(ValueError) as exc_info:
        _run(provider, "100", models=(FAST,))

    artifact = exc_info.value.live_run_artifact  # type: ignore[attr-defined]
    assert artifact.status is RunStatus.INCOMPLETE
    assert len(artifact.calls) == 2
    assert artifact.calls[0].cost_source is CostSource.PROVIDER
    assert artifact.calls[0].cost_usd == Decimal("0.01")
    assert artifact.calls[1].cost_source is CostSource.RESERVATION
    assert artifact.calls[1].error_kind == "crashed"
    # The reservation is the worst-case cost for one FAST call: 1000 tokens x $0.001 = $1.00.
    assert artifact.total_cost_usd == Decimal("0.01") + Decimal("1.00")


def test_keyboard_interrupt_mid_run_books_reservation_and_still_yields_an_artifact() -> None:
    provider = CrashingProvider(Decimal("0.01"), crash_at=3, exc_factory=KeyboardInterrupt)
    with pytest.raises(KeyboardInterrupt) as exc_info:
        _run(provider, "100", models=(FAST,))
    artifact = exc_info.value.live_run_artifact  # type: ignore[attr-defined]
    assert artifact.status is RunStatus.INCOMPLETE
    assert len(artifact.calls) == 3
    assert artifact.calls[-1].cost_source is CostSource.RESERVATION
    assert artifact.total_cost_usd >= Decimal("0.01") * 2 + Decimal("1.00")


FIXED_NOW = datetime(2026, 9, 14, 8, 30, tzinfo=UTC)


def test_main_writes_the_partial_artifact_when_run_live_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    chat: list[httpx.Request] = []
    _patch_main_offline(monkeypatch, tmp_path, _models_body(), chat)
    partial = make_artifact(status=RunStatus.INCOMPLETE, abort_reason="crashed: RuntimeError")

    def _crash(**kwargs: object) -> None:
        error = RuntimeError("simulated crash")
        error.live_run_artifact = partial  # type: ignore[attr-defined]
        raise error

    monkeypatch.setattr(live, "run_live", _crash)
    with pytest.raises(RuntimeError, match="simulated crash"):
        main(["--confirm-spend", "--output-dir", str(tmp_path)])
    written = tmp_path / f"{partial.run_id}.json"
    assert written.exists()
    assert load_run_artifact(written) == partial


@pytest.mark.parametrize("crash", [False, True])
def test_main_dumps_the_artifact_to_stderr_when_the_write_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    crash: bool,
) -> None:
    chat: list[httpx.Request] = []
    _patch_main_offline(monkeypatch, tmp_path, _models_body(), chat)
    artifact = make_artifact()

    def _run_live(**kwargs: object):  # type: ignore[no-untyped-def]
        if crash:
            error = RuntimeError("simulated crash")
            error.live_run_artifact = artifact  # type: ignore[attr-defined]
            raise error
        return artifact

    def _failing_write(*args: object, **kwargs: object) -> Path:
        raise OSError("disk full")

    monkeypatch.setattr(live, "run_live", _run_live)
    monkeypatch.setattr(live, "write_new_artifact", _failing_write)
    with pytest.raises(OSError, match="disk full"):
        main(["--confirm-spend", "--output-dir", str(tmp_path)])
    err = capsys.readouterr().err
    dumped = err[err.index("{") : err.rindex("}") + 1]
    assert RunArtifact.model_validate_json(dumped) == artifact
    assert "sk-test" not in err


def test_main_refuses_before_spend_when_the_target_artifact_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    chat: list[httpx.Request] = []
    _patch_main_offline(monkeypatch, tmp_path, _models_body(), chat)
    monkeypatch.setattr(live, "_utcnow", lambda: FIXED_NOW)
    existing = write_new_artifact(make_artifact(run_id="20260914T083000Z"), tmp_path)
    before = existing.read_text(encoding="utf-8")

    def _forbidden(**kwargs: object) -> None:
        raise AssertionError("run_live must not start")

    monkeypatch.setattr(live, "run_live", _forbidden)
    assert main(["--confirm-spend", "--output-dir", str(tmp_path)]) == 2
    assert chat == []
    assert existing.read_text(encoding="utf-8") == before
    assert "already exists" in capsys.readouterr().err


def test_main_refuses_before_spend_when_the_output_dir_is_not_writable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    chat: list[httpx.Request] = []
    _patch_main_offline(monkeypatch, tmp_path, _models_body(), chat)
    not_a_dir = tmp_path / "file"
    not_a_dir.write_text("x", encoding="utf-8")

    def _forbidden(**kwargs: object) -> None:
        raise AssertionError("run_live must not start")

    monkeypatch.setattr(live, "run_live", _forbidden)
    assert main(["--confirm-spend", "--output-dir", str(not_a_dir / "sub")]) == 2
    assert chat == []
    assert "not writable" in capsys.readouterr().err


def test_crash_handler_dumps_known_state_when_the_artifact_cannot_be_built(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def _broken_artifact(**kwargs: object) -> None:
        raise ValueError("simulated artifact validation failure")

    monkeypatch.setattr(live, "RunArtifact", _broken_artifact)
    provider = CrashingProvider(Decimal("0.01"), crash_at=3)
    with pytest.raises(RuntimeError, match="simulated crash") as exc_info:
        _run(provider, "100", models=(FAST,))
    assert getattr(exc_info.value, "live_run_artifact", None) is None
    err = capsys.readouterr().err
    dumped = json.loads(err[err.index("{") : err.rindex("}") + 1])
    assert dumped["run_id"] == CONTEXT.run_id
    assert dumped["status"] == "incomplete"
    assert "simulated artifact validation failure" in dumped["artifact_build_error"]
    assert [call["cost_source"] for call in dumped["calls"]] == [
        "provider",
        "provider",
        "reservation",
    ]
    assert Decimal(dumped["total_cost_usd"]) == Decimal("1.02")
