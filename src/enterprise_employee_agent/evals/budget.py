"""Budget guard for Issue #8 live runs: $0.50 cumulative across all runs.

Before each call, reserve its worst-case cost: UTF-8 bytes of the prompts plus a fixed message
overhead (bytes bound BPE tokens from above) at the input price, plus ``max_tokens`` at the output
price. Calls are sequential, so at most one reservation is open. After the call, the provider's
reported cost replaces the reservation; without a reported cost, the reservation is booked.
"""

# ANCHOR: worst_case_cost() is the pre-call estimate; BudgetLedger enforces it against the
# remaining budget (reserve() before the call, settle() after). spent_in_artifacts() sums
# total_cost_usd across every *.json under a directory to give the remaining budget at process
# start; Task 10 (live CLI) computes ISSUE_8_BUDGET_USD - spent_in_artifacts(...) once at
# startup and feeds it into a single BudgetLedger for the whole run.

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from enterprise_employee_agent.evals.artifact import load_run_artifact
from enterprise_employee_agent.llm.provider import AnswerRequest, ModelPricing

ISSUE_8_BUDGET_USD = Decimal("0.50")
MESSAGE_OVERHEAD_TOKENS = 64


class BudgetExceeded(Exception):
    """A call was not started because its worst-case cost would exceed the remaining budget."""


def worst_case_cost(request: AnswerRequest, pricing: ModelPricing) -> Decimal:
    input_upper_bound = (
        len(request.system_prompt.encode("utf-8"))
        + len(request.user_prompt.encode("utf-8"))
        + MESSAGE_OVERHEAD_TOKENS
    )
    return (
        Decimal(input_upper_bound) * pricing.prompt_usd_per_token
        + Decimal(request.model.max_tokens) * pricing.completion_usd_per_token
    )


class BudgetLedger:
    def __init__(self, remaining_usd: Decimal) -> None:
        self._remaining = remaining_usd
        self._spent = Decimal("0")
        self._open: Decimal | None = None

    @property
    def spent_usd(self) -> Decimal:
        return self._spent

    def reserve(self, amount: Decimal) -> None:
        if self._open is not None:
            raise RuntimeError("a reservation is already open; calls must be sequential")
        if self._spent + amount > self._remaining:
            raise BudgetExceeded(
                f"reservation ${amount} would exceed remaining ${self._remaining - self._spent}"
            )
        self._open = amount

    def settle(self, reserved: Decimal, actual: Decimal | None) -> Decimal:
        if self._open is None or self._open != reserved:
            raise RuntimeError("no open reservation matches this settlement")
        booked = actual if actual is not None else reserved
        self._spent += booked
        self._open = None
        return booked


def spent_in_artifacts(directory: Path) -> Decimal:
    if not directory.is_dir():
        return Decimal("0")
    return sum(
        (load_run_artifact(path).total_cost_usd for path in sorted(directory.glob("*.json"))),
        Decimal("0"),
    )
