"""Text report formatting for a scored micro-eval run."""

from __future__ import annotations

from enterprise_employee_agent.evals.scorer import EvalReport


def format_report(report: EvalReport) -> str:
    lines = [
        "Knowledge categories (offline scripted responses — exercises the pipeline, "
        "not a model; live baseline: evals/live.py):"
    ]
    for aggregate in report.knowledge:
        if aggregate.total == 0:
            lines.append(f"  {aggregate.category.value}: n/a (0 cases)")
        else:
            percentage = 100 * aggregate.passed / aggregate.total
            lines.append(
                f"  {aggregate.category.value}: {aggregate.passed}/{aggregate.total} "
                f"({percentage:.0f}%)"
            )

    lines.append("")
    lines.append("Deterministic safety:")
    if not report.safety_results:
        lines.append("  n/a (0 cases)")
    else:
        failing = [result for result in report.safety_results if not result.passed]
        if failing:
            lines.append("  FAIL")
            for result in failing:
                lines.append(
                    f"  - {result.case_id} ({result.category.value}): "
                    f"expected {result.expected_outcome!r}, got {result.actual_outcome!r}"
                )
        else:
            total = len(report.safety_results)
            lines.append(f"  PASS ({total}/{total})")

    return "\n".join(lines)
