"""Negative-path smoke coverage for the offline fake-adapter vertical slice (Issue #12).

Four independent checks: forbidden access (reusing the demo manifest's own negative cases),
a stale confirmation rejected without writing, duplicate/conflicting idempotent submission, and
a fake-provider failure the knowledge pipeline turns into an outcome instead of an exception.
"""

# ANCHOR: Companion to test_leave_journey_smoke.py (Issue #12). Each test is standalone and
# offline; none depends on the positive journey test's state.

from __future__ import annotations

from datetime import date, timedelta

import pytest
from conftest import NOW, _bind, _run

from enterprise_employee_agent.knowledge.answer import OutcomeKind, answer_question
from enterprise_employee_agent.leave.access_policy import (
    authorize_command,
    project_for,
    resolve_identity,
)
from enterprise_employee_agent.leave.contracts import (
    AccessAction,
    CommandName,
    ConfirmationEnvelope,
    ConfirmSubmitInput,
    CreateDraftInput,
    LeaveRequestPayload,
    LeaveStatus,
    RequestType,
    StartProcessingInput,
    UpdateDraftInput,
    WorkflowError,
    WorkflowErrorCode,
    build_leave_preview,
    payload_digest,
)
from enterprise_employee_agent.llm.provider import (
    AnswerRequest,
    ModelConfig,
    ProviderError,
    ProviderErrorKind,
    ProviderResponse,
)

_REQUEST_COUNTER = 0


def _payload(*, comment: str = "Operational note") -> LeaveRequestPayload:
    return LeaveRequestPayload(
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 5),
        request_type=RequestType.CONTINUOUS,
        employee_comment=comment,
    )


def _create_for(repository, manifest, employee_id: str):
    """Create and return a draft owned by ``employee_id``, via the real command path."""
    global _REQUEST_COUNTER
    _REQUEST_COUNTER += 1
    suffix = f"{_REQUEST_COUNTER:04d}"
    return _run(
        repository,
        manifest,
        employee_id,
        CreateDraftInput(
            expected_version=0,
            idempotency_key=f"create-negative-{suffix}",
            payload=_payload(),
        ),
        event_id=f"event-negative-create-{suffix}",
        occurred_at=NOW,
        generated_request_id=f"leave-negative-{suffix}",
    )


@pytest.mark.smoke
def test_forbidden_access_matches_the_manifests_own_negative_cases(repository, manifest) -> None:
    owned_requests: dict[str, object] = {}

    for case in manifest.negative_cases:
        if case.target_employee_id not in owned_requests:
            owned_requests[case.target_employee_id] = _create_for(
                repository, manifest, case.target_employee_id
            )
        target_request = owned_requests[case.target_employee_id]
        actor = resolve_identity(manifest, case.actor_id)

        if case.action is AccessAction.VIEW_REQUEST:
            with pytest.raises(WorkflowError) as excinfo:
                project_for(manifest, actor, target_request)
            assert excinfo.value.code is WorkflowErrorCode.NOT_FOUND
        elif case.action is AccessAction.START_PROCESSING:
            # authorize_command is a real public boundary (storage.execute calls it too), so
            # this is a genuine typed-error assertion, not a test-only shortcut.
            with pytest.raises(WorkflowError) as excinfo:
                authorize_command(manifest, actor, CommandName.START_PROCESSING, target_request)
            assert excinfo.value.code is WorkflowErrorCode.FORBIDDEN

            # The real composed path (bind_server_command -> repository.execute) never reaches
            # authorize_command for this case: _CommandContext.__post_init__ rejects a
            # role/command mismatch first, with the same typed FORBIDDEN error
            # authorize_command would raise (fixed as part of Issue #28).
            with pytest.raises(WorkflowError) as bind_excinfo:
                _bind(
                    manifest,
                    case.actor_id,
                    StartProcessingInput(
                        request_id=target_request.request_id,
                        expected_version=target_request.version,
                        idempotency_key="forbidden-start-processing-0001",
                    ),
                )
            assert bind_excinfo.value.code is WorkflowErrorCode.FORBIDDEN
        else:  # pragma: no cover - the demo manifest declares no other action
            pytest.fail(f"unhandled negative access action: {case.action}")


@pytest.mark.smoke
def test_stale_confirmation_is_rejected_without_writing(repository, manifest) -> None:
    created = _create_for(repository, manifest, "employee-alice")
    preview_v1 = build_leave_preview(created)

    bumped = _run(
        repository,
        manifest,
        "employee-alice",
        UpdateDraftInput(
            request_id=created.request_id,
            expected_version=1,
            idempotency_key="update-stale-confirmation-0001",
            payload=_payload(comment="Edited after the preview was taken"),
        ),
        event_id="event-stale-confirmation-0002",
        occurred_at=NOW + timedelta(minutes=1),
    )
    assert bumped.status is LeaveStatus.DRAFT
    assert bumped.version == 2

    with pytest.raises(WorkflowError) as excinfo:
        _run(
            repository,
            manifest,
            "employee-alice",
            ConfirmSubmitInput(
                request_id=created.request_id,
                expected_version=1,
                idempotency_key="submit-stale-confirmation-0001",
                confirmation=preview_v1.confirmation,
            ),
            event_id="event-stale-confirmation-0003",
            occurred_at=NOW + timedelta(minutes=2),
        )
    assert excinfo.value.code is WorkflowErrorCode.STALE_CONFIRMATION

    stored = repository.get(created.request_id)
    assert stored == bumped
    assert stored.version == 2
    assert stored.status is LeaveStatus.DRAFT


@pytest.mark.smoke
def test_duplicate_submission_replays_and_conflicting_payload_is_rejected(
    repository, manifest
) -> None:
    created = _create_for(repository, manifest, "employee-alice")
    preview = build_leave_preview(created)
    confirm_command = ConfirmSubmitInput(
        request_id=created.request_id,
        expected_version=1,
        idempotency_key="confirm-alice-0001",
        confirmation=preview.confirmation,
    )

    first = _run(
        repository,
        manifest,
        "employee-alice",
        confirm_command,
        event_id="event-duplicate-submit-0002",
        occurred_at=NOW + timedelta(minutes=1),
    )
    assert first.status is LeaveStatus.SUBMITTED
    assert first.version == 2
    assert len(first.audit_history) == 2

    replay = _run(
        repository,
        manifest,
        "employee-alice",
        confirm_command,
        event_id="event-duplicate-submit-unused",
        occurred_at=NOW + timedelta(minutes=2),
    )
    assert replay == first
    assert replay.version == 2
    assert len(replay.audit_history) == 2

    # Bonus: the same idempotency key with different intent (a different payload digest, so a
    # different command fingerprint) must not silently replay.
    conflicting = ConfirmSubmitInput(
        request_id=created.request_id,
        expected_version=1,
        idempotency_key="confirm-alice-0001",
        confirmation=ConfirmationEnvelope(
            request_id=created.request_id,
            request_version=1,
            payload_digest=payload_digest(_payload(comment="Different intent, same key")),
        ),
    )
    with pytest.raises(WorkflowError) as excinfo:
        _run(
            repository,
            manifest,
            "employee-alice",
            conflicting,
            event_id="event-duplicate-submit-conflict",
            occurred_at=NOW + timedelta(minutes=3),
        )
    assert excinfo.value.code is WorkflowErrorCode.IDEMPOTENCY_CONFLICT


class _AlwaysFailsProvider:
    """A local AnswerProvider that always raises ProviderError; never a real transport."""

    def complete(self, request: AnswerRequest) -> ProviderResponse:
        raise ProviderError(ProviderErrorKind.HTTP_ERROR, "simulated upstream failure")


@pytest.mark.smoke
def test_provider_failure_returns_an_outcome_and_touches_no_leave_request(
    repository, manifest, access_map
) -> None:
    created = _create_for(repository, manifest, "employee-alice")
    before = repository.get(created.request_id)

    outcome = answer_question(
        "How long is parental leave?",
        identity=resolve_identity(manifest, "employee-alice"),
        access_map=access_map,
        provider=_AlwaysFailsProvider(),
        model=ModelConfig(model_id="test/model", max_tokens=200, timeout_seconds=5.0),
    )

    assert outcome.kind is OutcomeKind.PROVIDER_ERROR
    assert outcome.error_kind is ProviderErrorKind.HTTP_ERROR
    assert outcome.answer is None
    assert outcome.abstained is False

    after = repository.get(created.request_id)
    assert after == before
    assert after.audit_history == before.audit_history
