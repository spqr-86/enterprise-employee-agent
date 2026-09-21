"""Integration tests for the atomic SQLite leave repository."""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from enterprise_employee_agent.leave.contracts import (
    CancelDraftInput,
    CommandName,
    ConfirmationEnvelope,
    ConfirmSubmitInput,
    CreateDraftInput,
    LeaveRequestPayload,
    LeaveStatus,
    ProvideClarificationInput,
    RequestClarificationInput,
    RequestType,
    StartProcessingInput,
    UpdateDraftInput,
    WorkflowError,
    WorkflowErrorCode,
    bind_server_command,
    load_demo_access_manifest,
    payload_digest,
)
from enterprise_employee_agent.storage.sqlite import SQLiteLeaveRepository

MANIFEST_PATH = Path("data/synthetic_protected/demo-access-v1.json")
NOW = datetime(2026, 9, 21, 10, 0, tzinfo=UTC)


@pytest.fixture()
def manifest():
    return load_demo_access_manifest(MANIFEST_PATH)


@pytest.fixture()
def repository(tmp_path: Path) -> SQLiteLeaveRepository:
    return SQLiteLeaveRepository(tmp_path / "leave.db")


def _payload(*, comment: str = "Operational note") -> LeaveRequestPayload:
    return LeaveRequestPayload(
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 5),
        request_type=RequestType.CONTINUOUS,
        employee_comment=comment,
    )


def _create(
    repository,
    manifest,
    *,
    request_id="leave-alice-001",
    actor_id="employee-alice",
    event_id="event-0001",
):
    command = bind_server_command(
        manifest,
        actor_id,
        CreateDraftInput(
            expected_version=0,
            idempotency_key="create-alice-0001",
            payload=_payload(),
        ),
        generated_request_id=request_id,
    )
    return repository.execute(manifest, command, event_id=event_id, occurred_at=NOW)


def _command(manifest, actor_id: str, command_input):
    return bind_server_command(manifest, actor_id, command_input)


def test_fresh_migration_is_reproducible_and_tracks_version(tmp_path: Path) -> None:
    database = tmp_path / "leave.db"
    first = SQLiteLeaveRepository(database)
    second = SQLiteLeaveRepository(database)

    assert first.schema_version() == 1
    assert second.schema_version() == 1


def test_recorded_migration_rejects_a_partial_schema(tmp_path: Path) -> None:
    database = tmp_path / "partial.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (1, ?)",
            (NOW.isoformat(),),
        )

    with pytest.raises(RuntimeError, match="does not match"):
        SQLiteLeaveRepository(database)


def test_request_and_audit_survive_repository_restart(repository, manifest) -> None:
    created = _create(repository, manifest)
    reopened = SQLiteLeaveRepository(repository.database_path)

    persisted = reopened.get("leave-alice-001")
    assert persisted == created
    assert persisted is not None
    assert persisted.audit_history[0].command is CommandName.CREATE_DRAFT


def test_update_and_every_declared_transition_are_persisted(repository, manifest) -> None:
    request = _create(repository, manifest)
    updated_payload = _payload(comment="Changed operational note")
    steps = [
        (
            "employee-alice",
            UpdateDraftInput(
                request_id=request.request_id,
                expected_version=1,
                idempotency_key="update-alice-0001",
                payload=updated_payload,
            ),
            "event-0002",
            LeaveStatus.DRAFT,
        ),
        (
            "employee-alice",
            ConfirmSubmitInput(
                request_id=request.request_id,
                expected_version=2,
                idempotency_key="submit-alice-0001",
                confirmation=ConfirmationEnvelope(
                    request_id=request.request_id,
                    request_version=2,
                    payload_digest=payload_digest(updated_payload),
                ),
            ),
            "event-0003",
            LeaveStatus.SUBMITTED,
        ),
        (
            "hr-harper",
            RequestClarificationInput(
                request_id=request.request_id,
                expected_version=3,
                idempotency_key="clarify-alice-0001",
                question="Please confirm the operational dates only.",
            ),
            "event-0004",
            LeaveStatus.NEEDS_CLARIFICATION,
        ),
        (
            "employee-alice",
            ProvideClarificationInput(
                request_id=request.request_id,
                expected_version=4,
                idempotency_key="answer-alice-0001",
                payload=updated_payload,
            ),
            "event-0005",
            LeaveStatus.NEEDS_CLARIFICATION,
        ),
        (
            "employee-alice",
            ConfirmSubmitInput(
                request_id=request.request_id,
                expected_version=5,
                idempotency_key="submit-alice-0002",
                confirmation=ConfirmationEnvelope(
                    request_id=request.request_id,
                    request_version=5,
                    payload_digest=payload_digest(updated_payload),
                ),
            ),
            "event-0006",
            LeaveStatus.SUBMITTED,
        ),
        (
            "hr-harper",
            StartProcessingInput(
                request_id=request.request_id,
                expected_version=6,
                idempotency_key="process-alice-0001",
            ),
            "event-0007",
            LeaveStatus.PROCESSING,
        ),
    ]

    for offset, (actor_id, command_input, event_id, expected_status) in enumerate(steps, start=1):
        request = repository.execute(
            manifest,
            _command(manifest, actor_id, command_input),
            event_id=event_id,
            occurred_at=NOW + timedelta(minutes=offset),
        )
        assert request.status is expected_status

    assert request.version == 7
    assert [event.request_version for event in request.audit_history] == [1, 2, 3, 4, 5, 6, 7]


def test_cancel_draft_is_terminal(repository, manifest) -> None:
    request = _create(repository, manifest)
    cancelled = repository.execute(
        manifest,
        _command(
            manifest,
            "employee-alice",
            CancelDraftInput(
                request_id=request.request_id,
                expected_version=1,
                idempotency_key="cancel-alice-0001",
            ),
        ),
        event_id="event-0002",
        occurred_at=NOW + timedelta(minutes=1),
    )
    assert cancelled.status is LeaveStatus.CANCELLED

    with pytest.raises(WorkflowError) as excinfo:
        repository.execute(
            manifest,
            _command(
                manifest,
                "employee-alice",
                CancelDraftInput(
                    request_id=request.request_id,
                    expected_version=2,
                    idempotency_key="cancel-alice-0002",
                ),
            ),
            event_id="event-0003",
            occurred_at=NOW + timedelta(minutes=2),
        )
    assert excinfo.value.code is WorkflowErrorCode.INVALID_TRANSITION


def test_stale_version_and_unauthorized_command_do_not_write(repository, manifest) -> None:
    request = _create(repository, manifest)
    stale = _command(
        manifest,
        "employee-alice",
        UpdateDraftInput(
            request_id=request.request_id,
            expected_version=99,
            idempotency_key="update-alice-0001",
            payload=_payload(comment="Must not persist"),
        ),
    )
    with pytest.raises(WorkflowError) as excinfo:
        repository.execute(
            manifest, stale, event_id="event-0002", occurred_at=NOW + timedelta(minutes=1)
        )
    assert excinfo.value.code is WorkflowErrorCode.VERSION_CONFLICT
    assert repository.get(request.request_id) == request

    # Alice cannot mutate Bob's request; access policy must run before transition logic.
    bob = _create(
        repository,
        manifest,
        request_id="leave-bob-001",
        actor_id="employee-bob",
        event_id="event-bob-0001",
    )
    cross_employee = _command(
        manifest,
        "employee-alice",
        UpdateDraftInput(
            request_id=bob.request_id,
            expected_version=1,
            idempotency_key="update-bob-0001",
            payload=_payload(comment="Must not persist either"),
        ),
    )
    with pytest.raises(WorkflowError) as excinfo:
        repository.execute(
            manifest,
            cross_employee,
            event_id="event-0003",
            occurred_at=NOW + timedelta(minutes=2),
        )
    assert excinfo.value.code is WorkflowErrorCode.NOT_FOUND
    assert repository.get(request.request_id) == request
    assert repository.get(bob.request_id) == bob


def test_audit_insert_failure_rolls_back_request_mutation(repository, manifest) -> None:
    original = _create(repository, manifest)
    with sqlite3.connect(repository.database_path) as connection:
        connection.execute(
            """
            CREATE TRIGGER fail_audit BEFORE INSERT ON audit_events
            BEGIN SELECT RAISE(ABORT, 'forced audit failure'); END
            """
        )

    command = _command(
        manifest,
        "employee-alice",
        UpdateDraftInput(
            request_id=original.request_id,
            expected_version=1,
            idempotency_key="update-alice-0001",
            payload=_payload(comment="Rolled back"),
        ),
    )
    with pytest.raises(sqlite3.IntegrityError, match="forced audit failure"):
        repository.execute(
            manifest, command, event_id="event-0002", occurred_at=NOW + timedelta(minutes=1)
        )

    assert repository.get(original.request_id) == original


def test_audit_schema_excludes_payload_question_and_hidden_reasoning(repository, manifest) -> None:
    _create(repository, manifest)
    with sqlite3.connect(repository.database_path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(audit_events)")}
        serialized = " ".join(
            str(value) for row in connection.execute("SELECT * FROM audit_events") for value in row
        )

    assert not {"payload", "employee_comment", "clarification_question", "reasoning"} & columns
    assert "Operational note" not in serialized


def test_audit_rows_are_append_only(repository, manifest) -> None:
    _create(repository, manifest)
    with sqlite3.connect(repository.database_path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "UPDATE audit_events SET actor_id = ? WHERE event_id = ?",
                ("attacker", "event-0001"),
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("DELETE FROM audit_events WHERE event_id = ?", ("event-0001",))
