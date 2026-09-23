"""Display-only view models for the demo templates (Issue #14)."""

# ANCHOR: Flat display data built from DemoApplication results. This is the filter that keeps
# AssistantFailure (detail, error_kind, violation_kind), provider status codes, and schema names
# out of every template: nothing here reads outcome.failure. Labels are code-owned and never
# imply eligibility or a real GitLab/HRIS integration.

from __future__ import annotations

from dataclasses import dataclass

from enterprise_employee_agent.app import AskResult, CitationInfo, IdentityOption
from enterprise_employee_agent.leave.assistant import AssistantOutcomeKind


@dataclass(frozen=True, slots=True)
class HeaderView:
    identity: IdentityOption | None
    mode_label: str
    identities: tuple[IdentityOption, ...]


@dataclass(frozen=True, slots=True)
class AnswerView:
    status_label: str
    answer_text: str | None
    clarifying_question: str | None
    guidance: str
    citations: tuple[CitationInfo, ...]


_OUTCOME_LABELS = {
    AssistantOutcomeKind.ANSWERED: "Answer from the handbook excerpt",
    AssistantOutcomeKind.ABSTAINED: "The available handbook excerpts do not answer this",
    AssistantOutcomeKind.ESCALATED: "This needs HR review",
    AssistantOutcomeKind.UNAVAILABLE: "The assistant is unavailable",
}


def answer_view(result: AskResult) -> AnswerView:
    outcome = result.outcome
    answer = outcome.answer
    return AnswerView(
        status_label=_OUTCOME_LABELS[outcome.kind],
        answer_text=answer.answer_text if answer is not None else None,
        clarifying_question=answer.clarifying_question if answer is not None else None,
        guidance=outcome.guidance,
        citations=result.citations,
    )
