"""Display-only view models for the demo templates (Issue #14)."""

# ANCHOR: Flat display data built from DemoApplication results. This is the filter that keeps
# AssistantFailure (detail, error_kind, violation_kind), provider status codes, and schema names
# out of every template: nothing here reads outcome.failure. Labels are code-owned and never
# imply eligibility or a real GitLab/HRIS integration.

from __future__ import annotations

from dataclasses import dataclass

from enterprise_employee_agent.app import AskResult, CitationInfo, IdentityOption, LeaveForm
from enterprise_employee_agent.leave.access_policy import LeaveProjection
from enterprise_employee_agent.leave.assistant import (
    AssistantOutcomeKind,
    FieldProposalOutcome,
    FieldProposalOutcomeKind,
)
from enterprise_employee_agent.leave.contracts import (
    ActorRole,
    CommandName,
    EmployeeLeaveProjection,
)


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


_PROPOSAL_FAILED_NOTE = (
    "The assistant could not read your description. Fill in the fields manually."
)
_PROPOSAL_INCOMPLETE_NOTE = "Some fields were not in your description. Fill in the empty fields."


def form_from_proposal(outcome: FieldProposalOutcome) -> tuple[LeaveForm, str | None]:
    proposal = outcome.proposal
    if outcome.kind is not FieldProposalOutcomeKind.PROPOSED or proposal is None:
        return LeaveForm(start_date="", end_date="", request_type=""), _PROPOSAL_FAILED_NOTE
    form = LeaveForm(
        start_date=proposal.start_date.isoformat() if proposal.start_date else "",
        end_date=proposal.end_date.isoformat() if proposal.end_date else "",
        request_type=proposal.request_type.value if proposal.request_type else "",
        employee_comment=proposal.employee_comment or "",
    )
    return form, _PROPOSAL_INCOMPLETE_NOTE if proposal.missing_fields() else None


def form_from_projection(projection: EmployeeLeaveProjection) -> LeaveForm:
    return LeaveForm(
        start_date=projection.start_date.isoformat(),
        end_date=projection.end_date.isoformat(),
        request_type=projection.request_type.value,
        employee_comment=projection.employee_comment or "",
    )


@dataclass(frozen=True, slots=True)
class RequestRow:
    request_id: str
    employee_id: str
    status: str
    start_date: str
    end_date: str
    request_type: str


def row_view(projection: LeaveProjection) -> RequestRow:
    return RequestRow(
        request_id=projection.request_id,
        employee_id=projection.employee_id,
        status=projection.status.value,
        start_date=projection.start_date.isoformat(),
        end_date=projection.end_date.isoformat(),
        request_type=projection.request_type.value,
    )


_LIST_HEADINGS = {
    ActorRole.EMPLOYEE: "Your leave requests",
    ActorRole.MANAGER: "Leave requests of your direct reports",
    ActorRole.HR: "Submitted leave requests",
}


def list_heading(role: ActorRole) -> str:
    return _LIST_HEADINGS[role]


# Every field any role projection declares; a new projection field without a label fails loudly.
_FIELD_LABELS = {
    "request_id": "Request",
    "employee_id": "Employee",
    "status": "Status",
    "version": "Version",
    "start_date": "Start date",
    "end_date": "End date",
    "request_type": "Leave type",
    "employee_comment": "Comment",
    "clarification_question": "HR question",
    "updated_at": "Last updated",
}
_HISTORY_FIELDS = {
    "action_history": "Your actions on this request",
    "audit_history": "Audit history",
}


@dataclass(frozen=True, slots=True)
class HistoryRow:
    occurred_at: str
    actor_id: str
    command: str
    new_status: str
    request_version: int


@dataclass(frozen=True, slots=True)
class RequestDetailView:
    request_id: str
    version: int | None
    fields: tuple[tuple[str, str], ...]
    history_label: str | None
    history: tuple[HistoryRow, ...]
    actions: frozenset[str]
    preview_version: int | None
    preview_digest: str | None
    form: LeaveForm | None


def detail_view(view) -> RequestDetailView:  # type: ignore[no-untyped-def]
    """Render exactly the fields of the role projection ``project_for`` returned."""

    view = view
    projection = view.projection
    data = projection.model_dump(mode="json")
    fields = tuple(
        (_FIELD_LABELS[name], "" if value is None else str(value))
        for name, value in data.items()
        if name not in _HISTORY_FIELDS
    )
    history_name = next((name for name in _HISTORY_FIELDS if name in data), None)
    events = getattr(projection, history_name) if history_name is not None else ()
    preview = view.preview
    form = None
    if CommandName.PROVIDE_CLARIFICATION in view.actions and isinstance(
        projection, EmployeeLeaveProjection
    ):
        form = form_from_projection(projection)
    return RequestDetailView(
        request_id=projection.request_id,
        version=getattr(projection, "version", None),
        fields=fields,
        history_label=_HISTORY_FIELDS[history_name] if history_name is not None else None,
        history=tuple(
            HistoryRow(
                occurred_at=event.occurred_at.isoformat(),
                actor_id=event.actor_id,
                command=event.command.value,
                new_status=event.new_status.value,
                request_version=event.request_version,
            )
            for event in events
        ),
        actions=frozenset(action.value for action in view.actions),
        preview_version=preview.request_version if preview is not None else None,
        preview_digest=preview.confirmation.payload_digest if preview is not None else None,
        form=form,
    )
