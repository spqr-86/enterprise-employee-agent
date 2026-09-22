"""Smoke test verifying integration conftest.py fixtures and helpers wire up correctly.

Pure scaffolding validation — no business logic, just proof that fixtures resolve and
helpers run without error.
"""

# ANCHOR: Minimal proof that integration/conftest.py exports and helpers work. Each
# fixture and helper is invoked at least once. Deliberately trivial: the assertion
# itself is tautological (before == before), its only purpose is to show the helper
# executes without exception.

from __future__ import annotations

from datetime import date

import pytest
from conftest import NOW, _run, assert_unchanged

from enterprise_employee_agent.leave.contracts import (
    CreateDraftInput,
    LeaveRequestPayload,
    RequestType,
)


@pytest.mark.smoke
def test_integration_fixtures_and_helpers_resolve(manifest, repository, access_map) -> None:
    """Verify all integration conftest fixtures and helpers are wired and callable."""
    # Prove manifest fixture works
    assert manifest is not None
    assert hasattr(manifest, "negative_cases")

    # Prove repository fixture works
    assert repository is not None

    # Prove access_map fixture works
    assert access_map is not None

    # Prove NOW constant is available and usable
    assert NOW is not None
    assert NOW.year == 2026

    # Prove _run helper works by creating a leave request
    payload = LeaveRequestPayload(
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 5),
        request_type=RequestType.CONTINUOUS,
        employee_comment="Smoke test",
    )
    created = _run(
        repository,
        manifest,
        "employee-alice",
        CreateDraftInput(
            expected_version=0,
            idempotency_key="smoke-conftest-test",
            payload=payload,
        ),
        event_id="event-smoke-conftest",
        occurred_at=NOW,
        generated_request_id="leave-smoke-conftest",
    )
    assert created is not None
    assert created.request_id == "leave-smoke-conftest"

    # Prove assert_unchanged helper works by calling it with before == after
    before = repository.get(created.request_id)
    assert_unchanged(repository, created.request_id, before)
