from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from artifact_factory import make_artifact

from enterprise_employee_agent.evals.budget import (
    MESSAGE_OVERHEAD_TOKENS,
    BudgetExceeded,
    BudgetLedger,
    spent_in_artifacts,
    worst_case_cost,
)
from enterprise_employee_agent.llm.provider import AnswerRequest, ModelConfig, ModelPricing


def test_worst_case_cost_uses_prompt_bytes_plus_overhead_and_max_tokens() -> None:
    request = AnswerRequest(
        model=ModelConfig(model_id="m", max_tokens=1000, timeout_seconds=1.0),
        system_prompt="ab",
        user_prompt="é",  # 2 UTF-8 bytes
        question="q",
        retrieved_ids=(),
    )
    pricing = ModelPricing(
        prompt_usd_per_token=Decimal("0.001"), completion_usd_per_token=Decimal("0.01")
    )
    expected = Decimal(4 + MESSAGE_OVERHEAD_TOKENS) * Decimal("0.001") + Decimal(1000) * Decimal(
        "0.01"
    )
    assert worst_case_cost(request, pricing) == expected


def test_reservation_that_exceeds_remaining_budget_is_refused() -> None:
    ledger = BudgetLedger(Decimal("1.00"))
    ledger.reserve(Decimal("0.60"))
    ledger.settle(Decimal("0.60"), Decimal("0.50"))
    with pytest.raises(BudgetExceeded):
        ledger.reserve(Decimal("0.51"))
    ledger.reserve(Decimal("0.50"))  # exactly at the limit is allowed


def test_actual_cost_replaces_reservation() -> None:
    ledger = BudgetLedger(Decimal("1.00"))
    ledger.reserve(Decimal("0.30"))
    assert ledger.settle(Decimal("0.30"), Decimal("0.01")) == Decimal("0.01")
    assert ledger.spent_usd == Decimal("0.01")


def test_missing_cost_books_the_reservation() -> None:
    ledger = BudgetLedger(Decimal("1.00"))
    ledger.reserve(Decimal("0.30"))
    assert ledger.settle(Decimal("0.30"), None) == Decimal("0.30")
    assert ledger.spent_usd == Decimal("0.30")


def test_settle_without_reservation_is_an_error() -> None:
    with pytest.raises(RuntimeError, match="no open reservation"):
        BudgetLedger(Decimal("1.00")).settle(Decimal("0.10"), None)


def test_cumulative_spend_is_read_from_existing_artifacts(tmp_path: Path) -> None:
    from enterprise_employee_agent.evals.artifact import write_new_artifact

    write_new_artifact(make_artifact(), tmp_path)
    write_new_artifact(make_artifact(run_id="20260913T130000Z"), tmp_path)
    (tmp_path / "20260913T120000Z-report.md").write_text("ignored", encoding="utf-8")
    assert spent_in_artifacts(tmp_path) == Decimal("0.000246")


def test_cumulative_spend_of_missing_directory_is_zero(tmp_path: Path) -> None:
    assert spent_in_artifacts(tmp_path / "absent") == Decimal("0")
