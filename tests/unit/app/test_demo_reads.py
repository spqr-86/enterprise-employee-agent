"""DemoApplication questions, field proposals, and role-scoped lists (Issue #14)."""

from __future__ import annotations

import itertools
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from enterprise_employee_agent.app import (
    DemoApplication,
    DemoSettings,
    LeaveForm,
    build_demo_application,
)
from enterprise_employee_agent.leave.assistant import (
    AssistantOutcomeKind,
    FieldProposalOutcomeKind,
)
from enterprise_employee_agent.leave.contracts import (
    HrLeaveProjection,
    ManagerLeaveProjection,
    WorkflowError,
    WorkflowErrorCode,
)
from enterprise_employee_agent.llm.provider import AnswerProvider
from enterprise_employee_agent.storage.sqlite import SQLiteLeaveRepository

NOW = datetime(2026, 9, 21, 10, 0, tzinfo=UTC)
US_DOC = "people-policies/leave-of-absence/us.md"
FORM = LeaveForm(start_date="2026-10-01", end_date="2026-10-05", request_type="continuous")


def _demo(tmp_path: Path, *, provider: AnswerProvider | None = None) -> DemoApplication:
    counter = itertools.count(1)
    return build_demo_application(
        DemoSettings(database_path=tmp_path / "demo.sqlite", openrouter_api_key=None),
        clock=lambda: NOW,
        id_factory=lambda prefix: f"{prefix}-{next(counter):04d}",
        provider=provider,
    )


def _submit(demo: DemoApplication, actor_id: str) -> str:
    preview = demo.create_draft(actor_id, FORM, f"create-{actor_id}")
    demo.confirm(
        actor_id,
        preview.request_id,
        1,
        preview.confirmation.payload_digest,
        f"confirm-{actor_id}",
    )
    return preview.request_id


def test_ask_scripted_question_returns_answer_with_citation_metadata(tmp_path) -> None:
    result = _demo(tmp_path).ask("employee-alice", "How long is parental leave in the US?")
    assert result.outcome.kind is AssistantOutcomeKind.ANSWERED
    assert [citation.document_id for citation in result.citations] == [US_DOC]
    citation = result.citations[0]
    assert citation.title == "United States Leave of Absence Policies"
    assert citation.source_url == (
        "https://handbook.gitlab.com/handbook/people-policies/leave-of-absence/us/"
    )
    assert citation.excerpt


def test_ask_unscripted_question_is_unavailable_not_a_crash(tmp_path) -> None:
    result = _demo(tmp_path).ask("employee-alice", "What is the weather today?")
    assert result.outcome.kind is AssistantOutcomeKind.UNAVAILABLE
    assert result.citations == ()


def test_ask_with_no_matching_evidence_abstains(tmp_path) -> None:
    result = _demo(tmp_path).ask("employee-alice", "zzqx")
    assert result.outcome.kind is AssistantOutcomeKind.ABSTAINED


def test_ask_rejects_unknown_actor(tmp_path) -> None:
    with pytest.raises(WorkflowError) as error:
        _demo(tmp_path).ask("nobody-here", "What is a leave of absence?")
    assert error.value.code is WorkflowErrorCode.UNAUTHORIZED


def test_propose_scripted_description(tmp_path) -> None:
    demo = _demo(tmp_path)
    outcome = demo.propose_fields("employee-alice", demo.suggested_leave_descriptions()[0])
    assert outcome.kind is FieldProposalOutcomeKind.PROPOSED
    assert outcome.proposal is not None
    assert outcome.proposal.missing_fields() == ()


def test_propose_unscripted_description_is_unavailable(tmp_path) -> None:
    outcome = _demo(tmp_path).propose_fields("employee-alice", "I need some time off.")
    assert outcome.kind is FieldProposalOutcomeKind.UNAVAILABLE
    assert outcome.proposal is None


def test_employee_list_contains_only_own_requests(tmp_path) -> None:
    demo = _demo(tmp_path)
    alice_request = _submit(demo, "employee-alice")
    _submit(demo, "employee-bob")
    assert [p.request_id for p in demo.requests_for("employee-alice")] == [alice_request]


def test_manager_list_contains_only_direct_reports(tmp_path) -> None:
    demo = _demo(tmp_path)
    alice_request = _submit(demo, "employee-alice")
    carol_request = _submit(demo, "employee-carol")
    morgan = demo.requests_for("manager-morgan")
    riley = demo.requests_for("manager-riley")
    assert [p.request_id for p in morgan] == [alice_request]
    assert [p.request_id for p in riley] == [carol_request]
    assert all(isinstance(p, ManagerLeaveProjection) for p in (*morgan, *riley))


def test_hr_list_excludes_drafts_and_cancelled(tmp_path) -> None:
    demo = _demo(tmp_path)
    submitted = _submit(demo, "employee-alice")
    demo.create_draft("employee-bob", FORM, "create-bob-draft")
    cancelled = demo.create_draft("employee-carol", FORM, "create-carol-draft")
    demo.cancel_draft("employee-carol", cancelled.request_id, 1, "cancel-carol-01")
    hr_list = demo.requests_for("hr-harper")
    assert [p.request_id for p in hr_list] == [submitted]
    assert isinstance(hr_list[0], HrLeaveProjection)


def test_list_storage_error_becomes_storage_unavailable(tmp_path, monkeypatch) -> None:
    demo = _demo(tmp_path)

    def broken(self):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(SQLiteLeaveRepository, "list_requests", broken)
    with pytest.raises(WorkflowError) as error:
        demo.requests_for("hr-harper")
    assert error.value.code is WorkflowErrorCode.STORAGE_UNAVAILABLE
