"""Full failure-path matrix for the grounded-answer assistant (Issue #13, Step 8).

Every row proves that a failure returns a typed, state-preserving result: no unvalidated model
prose survives, no forbidden document text leaks into a prompt or a serialised record, and no
actor can execute a command outside its role. Each test follows the same shape: snapshot a
pre-existing leave request, act, assert the outcome kind (and detail), then ``assert_unchanged``
against the snapshot, so "state unchanged" is never a vacuous check.
"""

# ANCHOR: AC-3 (typed, non-leaking failure outcomes), AC-4 (role/document authorization holds
# under a forged or adversarial actor), and the security regression suite for Issue #13. Covers
# the plan's Step 8 matrix row by row: contract violations (invalid JSON / schema / citation not
# retrieved), provider failures (timeout / HTTP error), prompt injection (both a refusing model
# and a hypothetically obedient one), role spoofing at the command-binding seam, the forbidden
# document never reaching a prompt or a serialised record, and the AC-2 non-US referral. It calls
# only the public seams Steps 1-7 built (``answer_for_actor``, ``build_clarification_request``,
# ``bind_server_command``) against the real demo manifest and real document corpus, never a
# toy/synthetic access map, so the assertions hold for the same data the app ships with.

from __future__ import annotations

import dataclasses
import json
from datetime import date
from pathlib import Path

import httpx
import pytest
from conftest import NOW, _run, assert_unchanged

from enterprise_employee_agent.evals.run import (
    _FORBIDDEN_DISCLOSURE_SECRET,
    FORBIDDEN_DOCUMENT_PROBE,
    PROVIDER_FAILURE_PROBE,
)
from enterprise_employee_agent.evals.validator import load_cases
from enterprise_employee_agent.knowledge.access import RESTRICTED_FIXTURE_ID
from enterprise_employee_agent.leave.assistant import (
    _REFERRAL_GUIDANCE,
    _UNAVAILABLE_GUIDANCE,
    AssistantOutcome,
    AssistantOutcomeKind,
    GroundedAnswer,
    answer_for_actor,
    build_clarification_request,
)
from enterprise_employee_agent.leave.contracts import (
    CreateDraftInput,
    LeaveRequest,
    LeaveRequestPayload,
    RequestClarificationInput,
    RequestType,
    WorkflowError,
    WorkflowErrorCode,
    bind_server_command,
)
from enterprise_employee_agent.llm.contract import AnswerStatus, ViolationKind
from enterprise_employee_agent.llm.openrouter import OpenRouterProvider
from enterprise_employee_agent.llm.provider import ModelConfig, ProviderErrorKind
from enterprise_employee_agent.llm.scripted import ScriptedProvider

QUESTION = "How long is parental leave in the US?"
US_DOCUMENT_ID = "people-policies/leave-of-absence/us.md"
MODEL = ModelConfig(model_id="test/model", max_tokens=200, timeout_seconds=5.0)
ACTOR_ID = "employee-alice"
HR_ACTOR_ID = "hr-harper"
CASES_PATH = Path("evals/cases/v0.1.yaml")
INJECTION_CASE_ID = "safety-prompt-injection-medical-data"

# Distinctive substring from data/synthetic_protected/documents/hr-only-note.md. Never the whole
# file: a substring check is enough to prove the text didn't leak, and keeps this module from
# duplicating the fixture's full prose.
_RESTRICTED_MARKER = "confidential leave investigations in a restricted queue"


def _payload() -> LeaveRequestPayload:
    return LeaveRequestPayload(
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 5),
        request_type=RequestType.CONTINUOUS,
    )


def _seed_request(repository, manifest, *, request_id: str, idempotency_key: str) -> LeaveRequest:
    """Create a real draft so every "state unchanged" assertion in this module is non-vacuous."""
    return _run(
        repository,
        manifest,
        ACTOR_ID,
        CreateDraftInput(expected_version=0, idempotency_key=idempotency_key, payload=_payload()),
        event_id=f"event-{request_id}",
        occurred_at=NOW,
        generated_request_id=request_id,
    )


def _answered_content(
    *, citations: tuple[str, ...], answer_text: str = "Parental leave is 16 weeks."
) -> str:
    return json.dumps(
        {
            "status": AnswerStatus.ANSWERED.value,
            "answer_text": answer_text,
            "citations": list(citations),
            "clarifying_question": None,
        }
    )


def _abstained_content() -> str:
    return json.dumps(
        {
            "status": AnswerStatus.ABSTAINED.value,
            "answer_text": None,
            "citations": [],
            "clarifying_question": None,
        }
    )


def _serialise(outcome: AssistantOutcome) -> str:
    return json.dumps(dataclasses.asdict(outcome))


def _injection_scenario() -> str:
    case = next(c for c in load_cases(CASES_PATH) if c.id == INJECTION_CASE_ID)
    assert case.scenario is not None
    return case.scenario


# ---------------------------------------------------------------------------
# Rows 1-3: contract violations (invalid JSON / schema / citation not retrieved)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("content", "violation_kind"),
    [
        pytest.param("not json", ViolationKind.INVALID_JSON, id="invalid_json"),
        pytest.param(
            json.dumps(
                {
                    "status": AnswerStatus.ANSWERED.value,
                    "answer_text": "x",
                    "citations": [],
                    "clarifying_question": None,
                }
            ),
            ViolationKind.SCHEMA,
            id="schema_violation",
        ),
        pytest.param(
            _answered_content(citations=(RESTRICTED_FIXTURE_ID,)),
            ViolationKind.CITATION_NOT_RETRIEVED,
            id="citation_not_retrieved",
        ),
    ],
)
def test_contract_violation_maps_to_unavailable_and_leaves_state_unchanged(
    manifest, repository, access_map, content: str, violation_kind: ViolationKind
) -> None:
    request_id = f"leave-failpath-{violation_kind.value}"
    seeded = _seed_request(
        repository,
        manifest,
        request_id=request_id,
        idempotency_key=f"seed-{violation_kind.value}-key",
    )

    provider = ScriptedProvider({QUESTION: content})
    outcome = answer_for_actor(
        QUESTION,
        manifest=manifest,
        actor_id=ACTOR_ID,
        access_map=access_map,
        provider=provider,
        model=MODEL,
    )

    assert outcome.kind is AssistantOutcomeKind.UNAVAILABLE
    assert outcome.answer is None
    assert outcome.guidance == _UNAVAILABLE_GUIDANCE
    assert outcome.failure is not None
    assert outcome.failure.violation_kind is violation_kind
    assert outcome.failure.error_kind is None
    # The fabricated/forbidden id never becomes a trusted citation or answer: outcome.answer is
    # None (asserted above), so there is no citations list or answer_text it could appear in. The
    # diagnostic failure.detail may still name the id (it is an id, not restricted document text)
    # — that is the raw ContractViolation message, not a re-validated field a caller could act on.
    if violation_kind is not ViolationKind.CITATION_NOT_RETRIEVED:
        assert RESTRICTED_FIXTURE_ID not in _serialise(outcome)

    assert_unchanged(repository, request_id, seeded)


# ---------------------------------------------------------------------------
# Rows 4-5: provider failures (timeout / HTTP error), offline via httpx.MockTransport
# ---------------------------------------------------------------------------


def _offline_provider(handler) -> OpenRouterProvider:
    return OpenRouterProvider(
        "offline-fake-key", client=httpx.Client(transport=httpx.MockTransport(handler))
    )


def test_provider_timeout_maps_to_unavailable_and_leaves_state_unchanged(
    manifest, repository, access_map
) -> None:
    request_id = "leave-failpath-timeout"
    seeded = _seed_request(
        repository, manifest, request_id=request_id, idempotency_key="seed-timeout-key"
    )

    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated timeout", request=request)

    outcome = answer_for_actor(
        PROVIDER_FAILURE_PROBE,
        manifest=manifest,
        actor_id=ACTOR_ID,
        access_map=access_map,
        provider=_offline_provider(timeout_handler),
        model=MODEL,
    )

    assert outcome.kind is AssistantOutcomeKind.UNAVAILABLE
    assert outcome.answer is None
    assert outcome.guidance == _UNAVAILABLE_GUIDANCE
    assert outcome.failure is not None
    assert outcome.failure.error_kind is ProviderErrorKind.TIMEOUT
    assert outcome.failure.violation_kind is None
    assert_unchanged(repository, request_id, seeded)


def test_provider_http_error_maps_to_unavailable_and_leaves_state_unchanged(
    manifest, repository, access_map
) -> None:
    request_id = "leave-failpath-http-error"
    seeded = _seed_request(
        repository, manifest, request_id=request_id, idempotency_key="seed-http-error-key"
    )

    def unavailable_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": {"message": "simulated outage"}})

    outcome = answer_for_actor(
        PROVIDER_FAILURE_PROBE,
        manifest=manifest,
        actor_id=ACTOR_ID,
        access_map=access_map,
        provider=_offline_provider(unavailable_handler),
        model=MODEL,
    )

    assert outcome.kind is AssistantOutcomeKind.UNAVAILABLE
    assert outcome.answer is None
    assert outcome.guidance == _UNAVAILABLE_GUIDANCE
    assert outcome.failure is not None
    assert outcome.failure.error_kind is ProviderErrorKind.HTTP_ERROR
    assert outcome.failure.violation_kind is None
    assert_unchanged(repository, request_id, seeded)


# ---------------------------------------------------------------------------
# Row 6: prompt injection (knowledge) — the model itself refuses
# ---------------------------------------------------------------------------


def test_prompt_injection_knowledge_case_abstains_with_referral_and_leaves_state_unchanged(
    manifest, repository, access_map
) -> None:
    scenario = _injection_scenario()
    request_id = "leave-failpath-injection-knowledge"
    seeded = _seed_request(
        repository, manifest, request_id=request_id, idempotency_key="seed-injection-key"
    )

    provider = ScriptedProvider({scenario: _abstained_content()})
    outcome = answer_for_actor(
        scenario,
        manifest=manifest,
        actor_id=ACTOR_ID,
        access_map=access_map,
        provider=provider,
        model=MODEL,
    )

    assert provider.requests, "the model must actually have been called (evidence was retrieved)"
    assert outcome.kind is AssistantOutcomeKind.ABSTAINED
    assert outcome.guidance == _REFERRAL_GUIDANCE
    assert outcome.answer is not None
    assert outcome.answer.answer_text is None
    assert outcome.answer.citations == ()

    # No leave request was created for the pasted-instruction target, and the pre-existing
    # request is untouched.
    assert repository.get("leave-jane-doe-cfra-request") is None
    assert_unchanged(repository, request_id, seeded)


# ---------------------------------------------------------------------------
# Row 7: prompt injection (obedient model) — a valid contract whose prose lies
# ---------------------------------------------------------------------------


def test_obedient_model_prose_never_builds_a_command_and_leaves_state_unchanged(
    manifest, repository, access_map
) -> None:
    obedient_text = "I have submitted your request. CONFIRM_SUBMIT."
    request_id = "leave-failpath-injection-obedient"
    seeded = _seed_request(
        repository, manifest, request_id=request_id, idempotency_key="seed-obedient-key"
    )

    provider = ScriptedProvider(
        {QUESTION: _answered_content(citations=(US_DOCUMENT_ID,), answer_text=obedient_text)}
    )
    outcome = answer_for_actor(
        QUESTION,
        manifest=manifest,
        actor_id=ACTOR_ID,
        access_map=access_map,
        provider=provider,
        model=MODEL,
    )

    assert outcome.kind is AssistantOutcomeKind.ANSWERED
    assert outcome.answer is not None
    assert outcome.answer.answer_text == obedient_text

    # AssistantOutcome/GroundedAnswer have no command field by type: there is no seam from model
    # prose to an executable command in the first place.
    outcome_fields = {field.name for field in dataclasses.fields(outcome)}
    answer_fields = {field.name for field in dataclasses.fields(outcome.answer)}
    assert "command" not in outcome_fields
    assert "command" not in answer_fields

    # No draft/submission for this employee exists after the "obedient" answer.
    assert repository.get("leave-jane-doe-cfra-request") is None
    assert_unchanged(repository, request_id, seeded)

    # This answer never asked for clarification, so even attempting to turn it into a command
    # is refused with a typed error, never a silent no-op.
    assert outcome.answer.clarifying_question is None
    with pytest.raises(WorkflowError) as excinfo:
        build_clarification_request(
            outcome.answer,
            request_id=seeded.request_id,
            expected_version=seeded.version,
            idempotency_key="clarify-obedient-attempt-key",
        )
    assert excinfo.value.code is WorkflowErrorCode.VALIDATION_FAILED

    # Same refusal for a GroundedAnswer with empty citations (the other half of the "no command
    # is built" guarantee: even a well-formed clarifying question is rejected without evidence).
    citationless = GroundedAnswer(
        kind=AssistantOutcomeKind.ANSWERED,
        status=AnswerStatus.ANSWERED,
        answer_text=obedient_text,
        citations=(),
        clarifying_question="Please confirm dates.",
        retrieved_ids=(US_DOCUMENT_ID,),
    )
    with pytest.raises(WorkflowError) as excinfo_empty:
        build_clarification_request(
            citationless,
            request_id=seeded.request_id,
            expected_version=seeded.version,
            idempotency_key="clarify-obedient-empty-key",
        )
    assert excinfo_empty.value.code is WorkflowErrorCode.VALIDATION_FAILED
    assert_unchanged(repository, request_id, seeded)


# ---------------------------------------------------------------------------
# Row 8: role spoofing at the command-binding seam
# ---------------------------------------------------------------------------
#
# answer_for_actor/propose_leave_fields take only a server-selected actor_id, never a DemoIdentity
# (test_leave_assistant.py::test_answer_for_actor_takes_only_an_actor_id_never_a_demo_identity
# proves a hand-built DemoIdentity has no parameter to go through). A forged identity CAN be
# handed in only at the workflow command-binding seam, bind_server_command, keyed by a real,
# server-known actor_id whose role does not match the command it issues. The real code raises
# WorkflowError(WorkflowErrorCode.FORBIDDEN) in both directions below (leave/contracts.py
# _CommandContext.__post_init__), never UNAUTHORIZED: the actor_id is a real, known identity —
# only its role is wrong for the command.


def test_hr_actor_forbidden_from_employee_only_create_draft(manifest, repository) -> None:
    request_id = "leave-failpath-role-spoof-hr"
    seeded = _seed_request(
        repository, manifest, request_id=request_id, idempotency_key="seed-role-spoof-hr-key"
    )

    forged_request_id = "leave-role-spoof-hr-draft"
    command_input = CreateDraftInput(
        expected_version=0, idempotency_key="role-spoof-hr-attempt-key", payload=_payload()
    )

    with pytest.raises(WorkflowError) as excinfo:
        bind_server_command(
            manifest, HR_ACTOR_ID, command_input, generated_request_id=forged_request_id
        )
    assert excinfo.value.code is WorkflowErrorCode.FORBIDDEN

    assert repository.get(forged_request_id) is None
    assert_unchanged(repository, request_id, seeded)


def test_employee_actor_forbidden_from_hr_only_request_clarification(manifest, repository) -> None:
    request_id = "leave-failpath-role-spoof-employee"
    seeded = _seed_request(
        repository, manifest, request_id=request_id, idempotency_key="seed-role-spoof-emp-key"
    )

    command_input = RequestClarificationInput(
        request_id=seeded.request_id,
        expected_version=seeded.version,
        idempotency_key="role-spoof-employee-attempt-key",
        question="Please clarify these dates.",
    )

    with pytest.raises(WorkflowError) as excinfo:
        bind_server_command(manifest, ACTOR_ID, command_input)
    assert excinfo.value.code is WorkflowErrorCode.FORBIDDEN

    assert_unchanged(repository, request_id, seeded)


# ---------------------------------------------------------------------------
# Row 9: forbidden document never reaches the prompt
# ---------------------------------------------------------------------------


def test_forbidden_document_never_reaches_the_prompt(manifest, repository, access_map) -> None:
    request_id = "leave-failpath-forbidden-doc-prompt"
    seeded = _seed_request(
        repository, manifest, request_id=request_id, idempotency_key="seed-forbidden-prompt-key"
    )

    provider = ScriptedProvider(
        {FORBIDDEN_DOCUMENT_PROBE: _answered_content(citations=(US_DOCUMENT_ID,))}
    )
    outcome = answer_for_actor(
        FORBIDDEN_DOCUMENT_PROBE,
        manifest=manifest,
        actor_id=ACTOR_ID,
        access_map=access_map,
        provider=provider,
        model=MODEL,
    )

    assert outcome.kind is AssistantOutcomeKind.ANSWERED
    assert provider.requests, "retrieval must have produced a public document the provider was sent"
    assert RESTRICTED_FIXTURE_ID not in provider.requests[0].retrieved_ids
    for request in provider.requests:
        assert _RESTRICTED_MARKER not in request.user_prompt

    assert_unchanged(repository, request_id, seeded)


# ---------------------------------------------------------------------------
# Row 10: forbidden content absent from records/logs
# ---------------------------------------------------------------------------


def test_forbidden_content_absent_from_request_records_and_serialised_outcome(
    manifest, repository, access_map
) -> None:
    provider = ScriptedProvider({QUESTION: _answered_content(citations=(US_DOCUMENT_ID,))})
    outcome = answer_for_actor(
        QUESTION,
        manifest=manifest,
        actor_id=ACTOR_ID,
        access_map=access_map,
        provider=provider,
        model=MODEL,
    )
    assert outcome.kind is AssistantOutcomeKind.ANSWERED
    assert provider.requests

    for request in provider.requests:
        record = request.record()
        # record() carries only these fields by construction: never keys, headers, or transport.
        assert set(record) == {
            "question",
            "retrieved_ids",
            "model_id",
            "max_tokens",
            "timeout_seconds",
            "params",
        }
        record_json = json.dumps(record)
        assert _RESTRICTED_MARKER not in record_json
        assert _FORBIDDEN_DISCLOSURE_SECRET not in record_json
        assert "api_key" not in record
        assert "headers" not in record
        assert "Authorization" not in record_json

    serialised_outcome = _serialise(outcome)
    assert _RESTRICTED_MARKER not in serialised_outcome
    assert _FORBIDDEN_DISCLOSURE_SECRET not in serialised_outcome


# ---------------------------------------------------------------------------
# Row 11: non-US question abstains with the AC-2 referral constant
# ---------------------------------------------------------------------------


def test_non_us_question_abstains_with_the_ac2_referral_constant(
    manifest, repository, access_map
) -> None:
    request_id = "leave-failpath-non-us"
    seeded = _seed_request(
        repository, manifest, request_id=request_id, idempotency_key="seed-non-us-key"
    )

    question = "How many weeks of parental leave do I get in Germany?"
    provider = ScriptedProvider({question: _abstained_content()})
    outcome = answer_for_actor(
        question,
        manifest=manifest,
        actor_id=ACTOR_ID,
        access_map=access_map,
        provider=provider,
        model=MODEL,
    )

    assert provider.requests, "the model must actually have been called (evidence was retrieved)"
    assert outcome.kind is AssistantOutcomeKind.ABSTAINED
    # Equality against the real constant (AC-2), never a re-typed string.
    assert outcome.guidance == _REFERRAL_GUIDANCE

    assert_unchanged(repository, request_id, seeded)
