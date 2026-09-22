from __future__ import annotations

import dataclasses
import inspect
import json
from pathlib import Path

import pytest

from enterprise_employee_agent.knowledge.access import (
    DocumentAccessMap,
    DocumentVisibility,
    KnowledgeDocument,
)
from enterprise_employee_agent.leave.assistant import (
    AssistantOutcomeKind,
    GroundedAnswer,
    answer_for_actor,
    build_clarification_request,
)
from enterprise_employee_agent.leave.contracts import (
    ActorRole,
    DemoAccessManifest,
    DemoIdentity,
    RequestClarificationInput,
    WorkflowError,
    WorkflowErrorCode,
    load_demo_access_manifest,
)
from enterprise_employee_agent.llm.contract import AnswerStatus
from enterprise_employee_agent.llm.provider import ModelConfig, ProviderErrorKind
from enterprise_employee_agent.llm.scripted import ScriptedProvider

MANIFEST_PATH = Path("data/synthetic_protected/demo-access-v1.json")
MODEL = ModelConfig(model_id="test/model", max_tokens=100, timeout_seconds=5.0)
QUESTION = "How many weeks of parental leave are paid?"
US = "people-policies/leave-of-absence/us.md"
US_TEXT = "Parental leave is 16 weeks and paid."
FORBIDDEN_DOCUMENT_PROBE = "Where is the HR-only note about confidential leave investigations?"
PUBLIC_PROBE_TEXT = (
    "Confidential leave investigations are handled by HR; general leave policy is public "
    "and available in the employee handbook."
)
HR_DOC_ID = "synthetic/hr-only-note"
SECRET_MARKER = "RESTRICTED-MARKER-7731"


def _manifest() -> DemoAccessManifest:
    return load_demo_access_manifest(MANIFEST_PATH)


def _access_map() -> DocumentAccessMap:
    return DocumentAccessMap(
        access_version="t",
        corpus_version="t",
        documents=(
            KnowledgeDocument(US, US_TEXT, DocumentVisibility.PUBLIC),
            KnowledgeDocument(
                HR_DOC_ID,
                f"{FORBIDDEN_DOCUMENT_PROBE} {SECRET_MARKER}",
                DocumentVisibility.HR_ONLY,
            ),
        ),
    )


def _probe_access_map() -> DocumentAccessMap:
    return DocumentAccessMap(
        access_version="t",
        corpus_version="t",
        documents=(
            KnowledgeDocument(US, PUBLIC_PROBE_TEXT, DocumentVisibility.PUBLIC),
            KnowledgeDocument(
                HR_DOC_ID,
                f"{FORBIDDEN_DOCUMENT_PROBE} {SECRET_MARKER}",
                DocumentVisibility.HR_ONLY,
            ),
        ),
    )


def _answered_content(*, citations: list[str], clarifying_question: str | None = None) -> str:
    return json.dumps(
        {
            "status": "answered",
            "answer_text": "Parental Leave is 16 weeks and paid.",
            "citations": citations,
            "clarifying_question": clarifying_question,
        }
    )


def _escalated_content() -> str:
    return json.dumps(
        {
            "status": "escalated",
            "answer_text": "This needs case-by-case review. Contact HR.",
            "citations": [US],
            "clarifying_question": None,
        }
    )


def _abstained_content() -> str:
    return json.dumps(
        {
            "status": "abstained",
            "answer_text": None,
            "citations": [],
            "clarifying_question": None,
        }
    )


def _serialise(outcome: object) -> str:
    return json.dumps(dataclasses.asdict(outcome))  # type: ignore[call-overload]


def test_answered_with_citations_propagates_verbatim() -> None:
    provider = ScriptedProvider({QUESTION: _answered_content(citations=[US])})
    outcome = answer_for_actor(
        QUESTION,
        manifest=_manifest(),
        actor_id="employee-alice",
        access_map=_access_map(),
        provider=provider,
        model=MODEL,
    )
    assert outcome.kind is AssistantOutcomeKind.ANSWERED
    assert outcome.answer is not None
    assert outcome.answer.citations == (US,)
    assert outcome.answer.answer_text == "Parental Leave is 16 weeks and paid."
    assert outcome.answer.clarifying_question is None
    assert outcome.answer.needs_clarification is False


def test_answered_with_clarifying_question_sets_needs_clarification() -> None:
    provider = ScriptedProvider(
        {
            QUESTION: _answered_content(
                citations=[US], clarifying_question="Continuous or intermittent?"
            )
        }
    )
    outcome = answer_for_actor(
        QUESTION,
        manifest=_manifest(),
        actor_id="employee-alice",
        access_map=_access_map(),
        provider=provider,
        model=MODEL,
    )
    assert outcome.kind is AssistantOutcomeKind.ANSWERED
    assert outcome.answer is not None
    assert outcome.answer.clarifying_question == "Continuous or intermittent?"
    assert outcome.answer.needs_clarification is True


def test_escalated_maps_to_escalated_kind_with_referral() -> None:
    provider = ScriptedProvider({QUESTION: _escalated_content()})
    outcome = answer_for_actor(
        QUESTION,
        manifest=_manifest(),
        actor_id="employee-alice",
        access_map=_access_map(),
        provider=provider,
        model=MODEL,
    )
    assert outcome.kind is AssistantOutcomeKind.ESCALATED
    assert outcome.answer is not None
    assert outcome.answer.citations == (US,)
    assert outcome.guidance
    assert "HR" in outcome.guidance or "Tilt" in outcome.guidance


def test_abstained_maps_to_abstained_kind_with_referral() -> None:
    # AC-2, Germany case: evidence is retrieved (shares tokens with the US doc) but the model
    # itself abstains because the question is out of the US document's jurisdiction.
    question = "How many weeks of parental leave do I get in Germany?"
    provider = ScriptedProvider({question: _abstained_content()})
    outcome = answer_for_actor(
        question,
        manifest=_manifest(),
        actor_id="employee-alice",
        access_map=_access_map(),
        provider=provider,
        model=MODEL,
    )
    assert outcome.kind is AssistantOutcomeKind.ABSTAINED
    assert outcome.answer is not None
    assert outcome.answer.citations == ()
    assert outcome.guidance
    assert "HR" in outcome.guidance or "Tilt" in outcome.guidance
    assert provider.requests, "the model must actually have been called"


def test_no_evidence_abstains_without_calling_the_provider() -> None:
    provider = ScriptedProvider({})
    outcome = answer_for_actor(
        "Completely unrelated question about office coffee machines",
        manifest=_manifest(),
        actor_id="employee-alice",
        access_map=_access_map(),
        provider=provider,
        model=MODEL,
    )
    assert outcome.kind is AssistantOutcomeKind.ABSTAINED
    assert provider.requests == []
    assert outcome.guidance


@pytest.mark.parametrize(
    "content",
    [
        "not json at all",
        json.dumps(
            {
                "status": "answered",
                "answer_text": None,
                "citations": [],
                "clarifying_question": None,
            }
        ),
        json.dumps(
            {
                "status": "answered",
                "answer_text": "x",
                "citations": [HR_DOC_ID],
                "clarifying_question": None,
            }
        ),
    ],
    ids=["invalid_json", "schema_violation", "citation_not_retrieved"],
)
def test_contract_violation_maps_to_unavailable_without_prose(content: str) -> None:
    provider = ScriptedProvider({QUESTION: content})
    outcome = answer_for_actor(
        QUESTION,
        manifest=_manifest(),
        actor_id="employee-alice",
        access_map=_access_map(),
        provider=provider,
        model=MODEL,
    )
    assert outcome.kind is AssistantOutcomeKind.UNAVAILABLE
    assert outcome.answer is None
    assert outcome.failure is not None
    assert outcome.failure.violation_kind is not None
    assert "not json" not in _serialise(outcome).lower() or content == "not json at all"


def test_provider_error_maps_to_unavailable_carrying_error_kind() -> None:
    class _FailingProvider:
        def __init__(self) -> None:
            self.requests: list[object] = []

        def complete(self, request: object) -> object:
            from enterprise_employee_agent.llm.provider import ProviderError

            self.requests.append(request)
            raise ProviderError(ProviderErrorKind.TIMEOUT, "simulated timeout")

    provider = _FailingProvider()
    outcome = answer_for_actor(
        QUESTION,
        manifest=_manifest(),
        actor_id="employee-alice",
        access_map=_access_map(),
        provider=provider,  # type: ignore[arg-type]
        model=MODEL,
    )
    assert outcome.kind is AssistantOutcomeKind.UNAVAILABLE
    assert outcome.answer is None
    assert outcome.failure is not None
    assert outcome.failure.error_kind is ProviderErrorKind.TIMEOUT
    assert outcome.failure.violation_kind is None


def test_unknown_actor_raises_unauthorized() -> None:
    provider = ScriptedProvider({})
    with pytest.raises(WorkflowError) as excinfo:
        answer_for_actor(
            QUESTION,
            manifest=_manifest(),
            actor_id="nobody-here",
            access_map=_access_map(),
            provider=provider,
            model=MODEL,
        )
    assert excinfo.value.code is WorkflowErrorCode.UNAUTHORIZED
    assert provider.requests == []


def test_answer_for_actor_takes_only_an_actor_id_never_a_demo_identity() -> None:
    parameters = inspect.signature(answer_for_actor).parameters
    assert "actor_id" in parameters
    assert "identity" not in parameters
    for parameter in parameters.values():
        assert parameter.annotation != DemoIdentity

    # A hand-built, forged DemoIdentity (e.g. an employee escalated to HR) has no parameter to
    # go through: answer_for_actor resolves identity itself from the manifest and actor_id.
    forged = DemoIdentity(
        identity_id="employee-alice", display_name="Alice Example", role=ActorRole.HR
    )
    assert forged.role is ActorRole.HR  # sanity: the forged object really claims HR
    with pytest.raises(TypeError):
        answer_for_actor(  # type: ignore[call-arg]
            QUESTION,
            manifest=_manifest(),
            identity=forged,
            access_map=_access_map(),
            provider=ScriptedProvider({}),
            model=MODEL,
        )


def test_forbidden_document_never_reaches_prompt_or_serialised_outcome() -> None:
    provider = ScriptedProvider(
        {
            FORBIDDEN_DOCUMENT_PROBE: _answered_content(citations=[US]),
        }
    )
    outcome = answer_for_actor(
        FORBIDDEN_DOCUMENT_PROBE,
        manifest=_manifest(),
        actor_id="employee-alice",
        access_map=_probe_access_map(),
        provider=provider,
        model=MODEL,
    )
    assert outcome.kind is AssistantOutcomeKind.ANSWERED
    assert provider.requests, "the public document must have been retrieved and sent"
    assert SECRET_MARKER not in provider.requests[0].user_prompt
    assert SECRET_MARKER not in _serialise(outcome)


# ---------------------------------------------------------------------------
# build_clarification_request (Step 5)
# ---------------------------------------------------------------------------

REQUEST_ID = "leave-alice-clarify-0001"
EXPECTED_VERSION = 2
IDEMPOTENCY_KEY = "clarify-alice-build-0001"


def _answered_grounded_answer(
    *,
    citations: tuple[str, ...] = (US,),
    clarifying_question: str | None = "Continuous or intermittent?",
) -> GroundedAnswer:
    return GroundedAnswer(
        kind=AssistantOutcomeKind.ANSWERED,
        status=AnswerStatus.ANSWERED,
        answer_text="Parental leave is 16 weeks and paid.",
        citations=citations,
        clarifying_question=clarifying_question,
        retrieved_ids=citations,
    )


def _build(answer: GroundedAnswer) -> RequestClarificationInput:
    return build_clarification_request(
        answer,
        request_id=REQUEST_ID,
        expected_version=EXPECTED_VERSION,
        idempotency_key=IDEMPOTENCY_KEY,
    )


def test_build_clarification_request_appends_a_code_built_source_suffix() -> None:
    answer = _answered_grounded_answer(
        citations=(US, HR_DOC_ID), clarifying_question="Continuous or intermittent?"
    )
    command_input = _build(answer)
    assert command_input.request_id == REQUEST_ID
    assert command_input.expected_version == EXPECTED_VERSION
    assert command_input.idempotency_key == IDEMPOTENCY_KEY
    assert command_input.question.startswith("Continuous or intermittent?")
    assert command_input.question.endswith(f" (source: {US}, {HR_DOC_ID})")
    # The suffix is built only from citation ids: the model's own text never contributes it.
    assert US_TEXT not in command_input.question


def test_build_clarification_request_rejects_empty_citations() -> None:
    answer = _answered_grounded_answer(citations=())
    with pytest.raises(WorkflowError) as excinfo:
        _build(answer)
    assert excinfo.value.code is WorkflowErrorCode.VALIDATION_FAILED


@pytest.mark.parametrize("clarifying_question", [None, "   "], ids=["none", "blank"])
def test_build_clarification_request_rejects_missing_clarifying_question(
    clarifying_question: str | None,
) -> None:
    answer = _answered_grounded_answer(clarifying_question=clarifying_question)
    with pytest.raises(WorkflowError) as excinfo:
        _build(answer)
    assert excinfo.value.code is WorkflowErrorCode.VALIDATION_FAILED


@pytest.mark.parametrize("kind", [AssistantOutcomeKind.UNAVAILABLE, AssistantOutcomeKind.ABSTAINED])
def test_build_clarification_request_rejects_unavailable_and_abstained_kinds(
    kind: AssistantOutcomeKind,
) -> None:
    answer = GroundedAnswer(
        kind=kind,
        status=AnswerStatus.ABSTAINED,
        answer_text=None,
        citations=(US,),
        clarifying_question="Continuous or intermittent?",
        retrieved_ids=(US,),
    )
    with pytest.raises(WorkflowError) as excinfo:
        _build(answer)
    assert excinfo.value.code is WorkflowErrorCode.VALIDATION_FAILED


def test_build_clarification_request_truncates_an_oversized_question_but_keeps_the_suffix() -> None:
    long_question = "Please clarify: " + ("word " * 200)  # ~900+ chars
    answer = _answered_grounded_answer(citations=(US, HR_DOC_ID), clarifying_question=long_question)
    command_input = _build(answer)
    assert len(command_input.question) <= 500
    # The citation suffix is never silently dropped, even when the question text is truncated.
    assert command_input.question.endswith(f" (source: {US}, {HR_DOC_ID})")
