"""Shared fixtures for the integration test layer (Issue #13).

Scaffolding for Steps 4, 5, 7, 8 of the grounded-answers integration plan. Deliberately
duplicated from tests/smoke/conftest.py to avoid making tests/conftest.py and the
ambiguous import it would create.
"""

# ANCHOR: Fixtures for integration tests that exercise the full workflow. Owns nothing
# production code doesn't already own: it only wires the same fixtures other tests use
# (the demo access manifest, a fresh SQLite repository, and the real knowledge access map)
# behind one clock. Also provides the _run helper and assert_unchanged for state snapshots.

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from enterprise_employee_agent.knowledge.access import DocumentAccessMap, load_document_access_map
from enterprise_employee_agent.leave.contracts import (
    ClientCommandInput,
    DemoAccessManifest,
    Identifier,
    LeaveRequest,
    bind_server_command,
    load_demo_access_manifest,
)
from enterprise_employee_agent.storage.sqlite import SQLiteLeaveRepository

MANIFEST_PATH = Path("data/synthetic_protected/demo-access-v1.json")
NOW = datetime(2026, 9, 21, 10, 0, tzinfo=UTC)


@pytest.fixture()
def manifest() -> DemoAccessManifest:
    return load_demo_access_manifest(MANIFEST_PATH)


@pytest.fixture()
def repository(tmp_path: Path) -> SQLiteLeaveRepository:
    return SQLiteLeaveRepository(tmp_path / "leave.db")


@pytest.fixture()
def access_map() -> DocumentAccessMap:
    return load_document_access_map()


def _bind(
    manifest: DemoAccessManifest,
    actor_id: Identifier,
    command_input: ClientCommandInput,
    **kwargs: object,
):
    """Thin wrapper over ``bind_server_command`` kept for call-site symmetry with ``_run``."""
    return bind_server_command(manifest, actor_id, command_input, **kwargs)


def _run(
    repository: SQLiteLeaveRepository,
    manifest: DemoAccessManifest,
    actor_id: Identifier,
    command_input: ClientCommandInput,
    *,
    event_id: str,
    occurred_at: datetime = NOW,
    **bind_kwargs: object,
) -> LeaveRequest:
    """Bind and execute one command in a single call.

    Justified by the positive journey test alone: it has 8+ call sites that would otherwise
    repeat ``bind_server_command`` + ``repository.execute`` verbatim.
    """
    command = _bind(manifest, actor_id, command_input, **bind_kwargs)
    return repository.execute(manifest, command, event_id=event_id, occurred_at=occurred_at)


def assert_unchanged(
    repository: SQLiteLeaveRepository,
    request_id: str,
    before: LeaveRequest,
) -> None:
    """Assert that a leave request has not changed, including audit history.

    Used by integration tests to verify that certain operations do not mutate the request.
    """
    after = repository.get(request_id)
    assert after == before
    assert after.audit_history == before.audit_history
