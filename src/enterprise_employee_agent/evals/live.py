"""Issue #8 live baseline run: 9 model-calling cases × 2 models, sequential, budget-guarded.

Refuses to start without ``--confirm-spend``, without ``OPENROUTER_API_KEY``, or with a dirty
working tree. Order: every case on the decision model, then every case on the comparison model,
so a budget abort loses comparison data before decision data. Writes one artifact to
``experiments/issue-8/<run_id>.json``.

Exit codes from ``main()``: 0 complete; 2 refused by preflight (no ``--confirm-spend``, no key,
dirty tree); 3 incomplete (including a budget refusal of the first call).
"""

# ANCHOR: The only script in this codebase allowed to spend money. run_live() is the pure,
# network-agnostic loop: it takes an already-constructed AnswerProvider and pricing, and is what
# tests/unit/test_live_run.py exercises with a scripted or MockTransport provider. main() is the
# thin, untested-by-network CLI shell: preflight refusals (--confirm-spend, API key, dirty tree)
# all return before any httpx.Client is constructed, so the refusal tests never touch the
# network. Task 11 (decision/report) is the only reader of the artifacts this module writes.

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import httpx

from enterprise_employee_agent.evals.artifact import (
    CostSource,
    ModelRunConfig,
    RunArtifact,
    RunStatus,
    call_record_from_outcome,
    write_new_artifact,
)
from enterprise_employee_agent.evals.budget import (
    ISSUE_8_BUDGET_USD,
    BudgetExceeded,
    BudgetLedger,
    spent_in_artifacts,
    worst_case_cost,
)
from enterprise_employee_agent.evals.run import CASES_PATH, EVAL_ROLE, calls_model, case_prompt
from enterprise_employee_agent.evals.schema import EvalCase
from enterprise_employee_agent.evals.validator import load_cases, validate_dataset
from enterprise_employee_agent.knowledge.access import DocumentAccessMap, load_document_access_map
from enterprise_employee_agent.knowledge.answer import PromptTemplate, answer_question, load_prompt
from enterprise_employee_agent.knowledge.corpus import load_manifest
from enterprise_employee_agent.knowledge.retrieval import DEFAULT_K, RETRIEVAL_VERSION
from enterprise_employee_agent.llm.openrouter import OpenRouterProvider, fetch_model_pricing
from enterprise_employee_agent.llm.provider import (
    AnswerProvider,
    AnswerRequest,
    ModelConfig,
    ModelPricing,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
EXPERIMENTS_DIR = _REPO_ROOT / "experiments" / "issue-8"

DECISION_MODEL = ModelConfig(
    model_id="openai/gpt-5-mini",
    max_tokens=4000,  # includes reasoning tokens
    timeout_seconds=120.0,
    extra_params={"reasoning_effort": "low"},  # the model does not accept temperature
)
COMPARISON_MODEL = ModelConfig(
    model_id="deepseek/deepseek-v3.2",
    max_tokens=1500,
    timeout_seconds=120.0,
    extra_params={"temperature": 0},
)
LIVE_MODELS = (DECISION_MODEL, COMPARISON_MODEL)

EXIT_COMPLETE = 0
EXIT_REFUSED = 2
EXIT_INCOMPLETE = 3


@dataclass(frozen=True, slots=True)
class RunContext:
    run_id: str
    started_at: datetime
    code_revision: str
    code_dirty: bool
    dataset_path: str
    dataset_sha256: str


def run_live(
    *,
    cases: Sequence[EvalCase],
    access_map: DocumentAccessMap,
    provider: AnswerProvider,
    models: Sequence[ModelConfig],
    pricing: Mapping[str, ModelPricing],
    remaining_budget_usd: Decimal,
    context: RunContext,
    prompt: PromptTemplate | None = None,
) -> RunArtifact:
    prompt = prompt if prompt is not None else load_prompt()
    ledger = BudgetLedger(remaining_budget_usd)
    selected = [case for case in cases if calls_model(case)]
    calls = []
    status = RunStatus.COMPLETE
    abort_reason: str | None = None

    for model in models:
        model_pricing = pricing[model.model_id]
        for case in selected:
            reservations: list[Decimal] = []

            def reserve(
                request: AnswerRequest, *, _reservations: list[Decimal] = reservations
            ) -> None:
                amount = worst_case_cost(request, model_pricing)
                ledger.reserve(amount)
                _reservations.append(amount)

            try:
                outcome = answer_question(
                    case_prompt(case),
                    role=EVAL_ROLE,
                    access_map=access_map,
                    provider=provider,
                    model=model,
                    prompt=prompt,
                    before_call=reserve,
                )
            except BudgetExceeded as error:
                status = RunStatus.INCOMPLETE
                abort_reason = f"budget: {error} (case {case.id}, model {model.model_id})"
                break

            if reservations:
                actual = outcome.response.usage.cost_usd if outcome.response is not None else None
                cost = ledger.settle(reservations[0], actual)
                source = CostSource.PROVIDER if actual is not None else CostSource.RESERVATION
                reserved: Decimal | None = reservations[0]
            else:
                cost, source, reserved = Decimal("0"), CostSource.NONE, None
            calls.append(
                call_record_from_outcome(
                    case.id,
                    model.model_id,
                    outcome,
                    reserved_usd=reserved,
                    cost_usd=cost,
                    cost_source=source,
                )
            )
        if status is RunStatus.INCOMPLETE:
            break

    return RunArtifact(
        run_id=context.run_id,
        started_at=context.started_at,
        code_revision=context.code_revision,
        code_dirty=context.code_dirty,
        corpus_version=access_map.corpus_version,
        access_version=access_map.access_version,
        dataset_path=context.dataset_path,
        dataset_sha256=context.dataset_sha256,
        prompt_version=prompt.version,
        prompt_sha256=prompt.sha256,
        retrieval_version=RETRIEVAL_VERSION,
        k=DEFAULT_K,
        eval_role=EVAL_ROLE.value,
        decision_model_id=models[0].model_id,
        models=tuple(
            ModelRunConfig(
                model_id=model.model_id,
                max_tokens=model.max_tokens,
                timeout_seconds=model.timeout_seconds,
                params=dict(model.extra_params),
                prompt_usd_per_token=pricing[model.model_id].prompt_usd_per_token,
                completion_usd_per_token=pricing[model.model_id].completion_usd_per_token,
            )
            for model in models
        ),
        budget_total_usd=ISSUE_8_BUDGET_USD,
        budget_remaining_at_start_usd=remaining_budget_usd,
        status=status,
        abort_reason=abort_reason,
        calls=tuple(calls),
    )


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=_REPO_ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the paid Issue #8 live baseline. Exit codes: 0 complete; "
            "2 refused by preflight (no --confirm-spend, no key, dirty tree); "
            "3 incomplete (including a budget refusal of the first call)."
        )
    )
    parser.add_argument(
        "--confirm-spend",
        action="store_true",
        help="required acknowledgement that this run spends real money",
    )
    parser.add_argument("--output-dir", type=Path, default=EXPERIMENTS_DIR)
    args = parser.parse_args(argv)

    if not args.confirm_spend:
        print("refusing to start a paid run without --confirm-spend", file=sys.stderr)
        return EXIT_REFUSED
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("OPENROUTER_API_KEY is not set", file=sys.stderr)
        return EXIT_REFUSED
    if _git("status", "--porcelain"):
        print("working tree is dirty; commit first so the run is reproducible", file=sys.stderr)
        return EXIT_REFUSED

    cases = load_cases(CASES_PATH)
    validate_dataset(cases, frozenset(document.id for document in load_manifest().documents))
    access_map = load_document_access_map()
    remaining = ISSUE_8_BUDGET_USD - spent_in_artifacts(args.output_dir)
    started_at = datetime.now(UTC)
    context = RunContext(
        run_id=started_at.strftime("%Y%m%dT%H%M%SZ"),
        started_at=started_at,
        code_revision=_git("rev-parse", "HEAD"),
        code_dirty=False,
        dataset_path=CASES_PATH.relative_to(_REPO_ROOT).as_posix(),
        dataset_sha256=hashlib.sha256(CASES_PATH.read_bytes()).hexdigest(),
    )
    print(f"remaining Issue #8 budget: ${remaining}")

    with httpx.Client() as client:
        pricing = fetch_model_pricing([model.model_id for model in LIVE_MODELS], client=client)
        artifact = run_live(
            cases=cases,
            access_map=access_map,
            provider=OpenRouterProvider(api_key, client=client),
            models=LIVE_MODELS,
            pricing=pricing,
            remaining_budget_usd=remaining,
            context=context,
        )
    path = write_new_artifact(artifact, args.output_dir)
    print(
        f"{artifact.status.value}: {len(artifact.calls)} calls, "
        f"cost ${artifact.total_cost_usd} -> {path}"
    )
    return EXIT_COMPLETE if artifact.status is RunStatus.COMPLETE else EXIT_INCOMPLETE


if __name__ == "__main__":
    raise SystemExit(main())
