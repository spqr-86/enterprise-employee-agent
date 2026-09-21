"""Atomic SQLite persistence for the v0.1 leave workflow."""

# ANCHOR: Owns reproducible SQLite migrations and one authorized command transaction that writes
# the LeaveRequest mutation plus its append-only AuditEvent. Audit rows intentionally exclude
# payload text, clarification text, provider output, and hidden reasoning.

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from enterprise_employee_agent.leave.access_policy import authorize_command, authorize_replay
from enterprise_employee_agent.leave.contracts import (
    CancelDraftInput,
    ConfirmSubmitInput,
    CreateDraftInput,
    DemoAccessManifest,
    LeaveRequest,
    LeaveRequestPayload,
    ProvideClarificationInput,
    RequestClarificationInput,
    UpdateDraftInput,
    WorkflowError,
    WorkflowErrorCode,
    _CommandContext,
    _require_bound_command,
    build_audit_event,
    command_fingerprint,
)
from enterprise_employee_agent.leave.state_machine import transition_target

_LATEST_SCHEMA_VERSION = 2
_MIGRATION_1 = (
    """CREATE TABLE leave_requests (
    request_id TEXT PRIMARY KEY,
    employee_id TEXT NOT NULL,
    status TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version >= 1),
    payload_json TEXT NOT NULL,
    clarification_question TEXT,
    updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE audit_events (
    event_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL REFERENCES leave_requests(request_id),
    actor_id TEXT NOT NULL,
    command TEXT NOT NULL,
    previous_status TEXT,
    new_status TEXT NOT NULL,
    previous_version INTEGER NOT NULL CHECK (previous_version >= 0),
    request_version INTEGER NOT NULL CHECK (request_version >= 1),
    idempotency_key TEXT NOT NULL,
    command_fingerprint TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    UNIQUE (request_id, request_version)
    )""",
    """CREATE INDEX audit_events_request_order
    ON audit_events(request_id, request_version)""",
    """CREATE TRIGGER audit_events_no_update
    BEFORE UPDATE ON audit_events
    BEGIN SELECT RAISE(ABORT, 'audit events are append-only'); END""",
    """CREATE TRIGGER audit_events_no_delete
    BEFORE DELETE ON audit_events
    BEGIN SELECT RAISE(ABORT, 'audit events are append-only'); END""",
)
_MIGRATION_2 = (
    """CREATE TABLE idempotency_records (
    actor_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    command_fingerprint TEXT NOT NULL,
    request_id TEXT NOT NULL REFERENCES leave_requests(request_id),
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (actor_id, operation, idempotency_key)
    )""",
    """CREATE INDEX idempotency_records_request
    ON idempotency_records(request_id)""",
    """CREATE TRIGGER idempotency_records_no_update
    BEFORE UPDATE ON idempotency_records
    BEGIN SELECT RAISE(ABORT, 'idempotency records are append-only'); END""",
    """CREATE TRIGGER idempotency_records_no_delete
    BEFORE DELETE ON idempotency_records
    BEGIN SELECT RAISE(ABORT, 'idempotency records are append-only'); END""",
)
_MIGRATIONS = {1: _MIGRATION_1, 2: _MIGRATION_2}
_EXPECTED_SCHEMA_OBJECTS = {
    ("table", "leave_requests"),
    ("table", "audit_events"),
    ("index", "audit_events_request_order"),
    ("trigger", "audit_events_no_update"),
    ("trigger", "audit_events_no_delete"),
    ("table", "idempotency_records"),
    ("index", "idempotency_records_request"),
    ("trigger", "idempotency_records_no_update"),
    ("trigger", "idempotency_records_no_delete"),
}


class SQLiteLeaveRepository:
    """Persist leave requests and their audit history in one local SQLite database."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _migrate(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )"""
            )
            row = connection.execute(
                "SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations"
            ).fetchone()
            current_version = int(row["version"])
            if current_version > _LATEST_SCHEMA_VERSION:
                raise RuntimeError("database schema is newer than this application")
            for version in range(current_version + 1, _LATEST_SCHEMA_VERSION + 1):
                try:
                    connection.execute("BEGIN IMMEDIATE")
                    for statement in _MIGRATIONS[version]:
                        connection.execute(statement)
                    connection.execute(
                        "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                        (version, datetime.now().astimezone().isoformat()),
                    )
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
            self._validate_schema(connection)

    @staticmethod
    def _validate_schema(connection: sqlite3.Connection) -> None:
        placeholders = ", ".join("?" for _ in _EXPECTED_SCHEMA_OBJECTS)
        rows = connection.execute(
            f"SELECT type, name FROM sqlite_master WHERE name IN ({placeholders})",
            tuple(name for _, name in sorted(_EXPECTED_SCHEMA_OBJECTS)),
        ).fetchall()
        actual = {(row["type"], row["name"]) for row in rows}
        if actual != _EXPECTED_SCHEMA_OBJECTS:
            raise RuntimeError("database schema does not match recorded migration version")

    def schema_version(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT MAX(version) AS version FROM schema_migrations"
            ).fetchone()
        return int(row["version"])

    def get(self, request_id: str) -> LeaveRequest | None:
        """Load an internal full record; callers must authorize before projection or return."""

        with self._connect() as connection:
            return self._get(connection, request_id)

    def execute(
        self,
        manifest: DemoAccessManifest,
        command: _CommandContext,
        *,
        event_id: str,
        occurred_at: datetime,
    ) -> LeaveRequest:
        """Authorize and atomically persist one typed mutation and its audit event.

        HTTP/UI composition belongs to Issue #12 and must project the returned full record.
        """

        bound = _require_bound_command(command)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = self._get(connection, bound.request_id)
            authorize_command(manifest, bound.actor, bound.input.command, current)
            replay = self._idempotent_replay(connection, manifest, bound)
            if replay is not None:
                return replay

            if isinstance(bound.input, CreateDraftInput):
                if current is not None:
                    raise WorkflowError(WorkflowErrorCode.VERSION_CONFLICT)
                updated = LeaveRequest(
                    request_id=bound.request_id,
                    employee_id=bound.actor.identity_id,
                    status="draft",
                    version=1,
                    payload=bound.input.payload,
                    clarification_question=None,
                    updated_at=occurred_at,
                    audit_history=(),
                )
                previous_status = None
                previous_version = 0
                self._insert_request(connection, updated)
            else:
                if current is None:
                    raise WorkflowError(WorkflowErrorCode.NOT_FOUND)
                if current.version != bound.input.expected_version:
                    raise WorkflowError(WorkflowErrorCode.VERSION_CONFLICT)
                if isinstance(
                    bound.input, ConfirmSubmitInput
                ) and not bound.input.confirmation.matches(
                    request_id=current.request_id,
                    payload=current.payload,
                    request_version=current.version,
                ):
                    raise WorkflowError(WorkflowErrorCode.STALE_CONFIRMATION)
                previous_status = current.status
                previous_version = current.version
                updated = self._apply_existing(current, bound, occurred_at)
                cursor = connection.execute(
                    """
                    UPDATE leave_requests
                    SET status = ?, version = ?, payload_json = ?, clarification_question = ?,
                        updated_at = ?
                    WHERE request_id = ? AND version = ?
                    """,
                    (
                        updated.status,
                        updated.version,
                        updated.payload.model_dump_json(),
                        updated.clarification_question,
                        updated.updated_at.isoformat(),
                        updated.request_id,
                        previous_version,
                    ),
                )
                if cursor.rowcount != 1:
                    raise WorkflowError(WorkflowErrorCode.VERSION_CONFLICT)

            event = build_audit_event(
                bound,
                event_id=event_id,
                previous_status=previous_status,
                new_status=updated.status,
                previous_version=previous_version,
                request_version=updated.version,
                occurred_at=occurred_at,
            )
            connection.execute(
                """
                INSERT INTO audit_events(
                    event_id, request_id, actor_id, command, previous_status, new_status,
                    previous_version, request_version, idempotency_key, command_fingerprint,
                    occurred_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.request_id,
                    event.actor_id,
                    event.command,
                    event.previous_status,
                    event.new_status,
                    event.previous_version,
                    event.request_version,
                    event.idempotency_key,
                    event.command_fingerprint,
                    event.occurred_at.isoformat(),
                ),
            )
            persisted = self._get(connection, updated.request_id)
            assert persisted is not None
            connection.execute(
                """
                INSERT INTO idempotency_records(
                    actor_id, operation, idempotency_key, command_fingerprint,
                    request_id, result_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    bound.actor.identity_id,
                    bound.input.command,
                    bound.input.idempotency_key,
                    command_fingerprint(bound),
                    persisted.request_id,
                    persisted.model_dump_json(),
                    occurred_at.isoformat(),
                ),
            )
            return persisted

    def _idempotent_replay(
        self,
        connection: sqlite3.Connection,
        manifest: DemoAccessManifest,
        command: _CommandContext,
    ) -> LeaveRequest | None:
        row = connection.execute(
            """
            SELECT command_fingerprint, request_id, result_json
            FROM idempotency_records
            WHERE actor_id = ? AND operation = ? AND idempotency_key = ?
            """,
            (
                command.actor.identity_id,
                command.input.command,
                command.input.idempotency_key,
            ),
        ).fetchone()
        if row is None:
            return None
        stored_request = self._get(connection, row["request_id"])
        if stored_request is None:
            raise WorkflowError(WorkflowErrorCode.NOT_FOUND)
        authorize_replay(manifest, command.actor, stored_request)
        if row["command_fingerprint"] != command_fingerprint(command):
            raise WorkflowError(WorkflowErrorCode.IDEMPOTENCY_CONFLICT)
        return LeaveRequest.model_validate_json(row["result_json"])

    @staticmethod
    def _apply_existing(
        current: LeaveRequest, command: _CommandContext, occurred_at: datetime
    ) -> LeaveRequest:
        target = transition_target(current, command.input.command)
        payload = current.payload
        clarification_question = current.clarification_question
        if isinstance(command.input, UpdateDraftInput | ProvideClarificationInput):
            payload = command.input.payload
        if isinstance(command.input, RequestClarificationInput):
            clarification_question = command.input.question
        elif isinstance(command.input, ConfirmSubmitInput | CancelDraftInput):
            clarification_question = None
        return current.model_copy(
            update={
                "status": target,
                "version": current.version + 1,
                "payload": payload,
                "clarification_question": clarification_question,
                "updated_at": occurred_at,
            }
        )

    @staticmethod
    def _insert_request(connection: sqlite3.Connection, request: LeaveRequest) -> None:
        connection.execute(
            """
            INSERT INTO leave_requests(
                request_id, employee_id, status, version, payload_json,
                clarification_question, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                request.request_id,
                request.employee_id,
                request.status,
                request.version,
                request.payload.model_dump_json(),
                request.clarification_question,
                request.updated_at.isoformat(),
            ),
        )

    @staticmethod
    def _get(connection: sqlite3.Connection, request_id: str) -> LeaveRequest | None:
        row = connection.execute(
            """
            SELECT request_id, employee_id, status, version, payload_json,
                   clarification_question, updated_at
            FROM leave_requests WHERE request_id = ?
            """,
            (request_id,),
        ).fetchone()
        if row is None:
            return None
        event_rows = connection.execute(
            """
            SELECT event_id, request_id, actor_id, command, previous_status, new_status,
                   previous_version, request_version, idempotency_key, command_fingerprint,
                   occurred_at
            FROM audit_events WHERE request_id = ? ORDER BY request_version
            """,
            (request_id,),
        ).fetchall()
        return LeaveRequest.model_validate(
            {
                "request_id": row["request_id"],
                "employee_id": row["employee_id"],
                "status": row["status"],
                "version": row["version"],
                "payload": LeaveRequestPayload.model_validate_json(row["payload_json"]),
                "clarification_question": row["clarification_question"],
                "updated_at": row["updated_at"],
                "audit_history": [dict(event_row) for event_row in event_rows],
            }
        )
