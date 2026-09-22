"""Grounded-answer orchestration for the leave workflow (Issue #13).

Wraps ``knowledge.answer.answer_question`` in a deterministic outcome-mapping layer the leave
workflow can consume safely. Two invariants this module exists to enforce:

- unvalidated model prose never survives into the outcome: a contract violation or provider
  failure always maps to ``UNAVAILABLE`` with ``answer is None``, never a half-parsed
  ``answer_text``;
- identity is never accepted from the caller as a ``DemoIdentity`` (which is a plain, forgeable
  pydantic model outside of ``bind_server_command``'s token-gated path). ``answer_for_actor``
  takes only a server-selected ``actor_id`` and resolves it itself via
  ``access_policy.resolve_identity``, exactly like ``bind_server_command`` does for commands.

This module owns no eligibility or jurisdiction logic: whether a question is answerable is
decided only by the model's own ``AnswerStatus`` plus the retrieval access filter upstream. The
only code-owned judgement here is the deterministic ``(OutcomeKind, AnswerStatus | None)`` ->
``AssistantOutcomeKind`` mapping and the referral guidance text.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from pydantic import ValidationError

from enterprise_employee_agent.knowledge.access import DocumentAccessMap
from enterprise_employee_agent.knowledge.answer import (
    DEFAULT_K,
    OutcomeKind,
    PromptTemplate,
    answer_question,
)
from enterprise_employee_agent.leave.access_policy import resolve_identity
from enterprise_employee_agent.leave.contracts import (
    CreateDraftInput,
    DemoAccessManifest,
    IdempotencyKey,
    Identifier,
    LeaveRequestPayload,
    LeaveRequestPreview,
    ProvideClarificationInput,
    RequestClarificationInput,
    WorkflowError,
    WorkflowErrorCode,
    bind_server_command,
    build_leave_preview,
)
from enterprise_employee_agent.llm.contract import AnswerStatus, ViolationKind
from enterprise_employee_agent.llm.provider import AnswerProvider, ModelConfig, ProviderErrorKind
from enterprise_employee_agent.storage.sqlite import SQLiteLeaveRepository

# RequestClarificationInput.question's own hard limit (leave/contracts.py:227); this module
# truncates against it directly rather than importing pydantic's field metadata.
_QUESTION_MAX_LENGTH = 500

# Code-owned referral text. Never model-generated prose (D-D): shown whenever the assistant
# cannot, or should not, give a grounded answer of its own.
_REFERRAL_GUIDANCE = "This is out of scope for the assistant. Contact HR (or Tilt) for help."
_ANSWERED_GUIDANCE = (
    "This answer is grounded in the cited policy documents; review them for full details."
)
_UNAVAILABLE_GUIDANCE = "The assistant could not answer right now. Contact HR (or Tilt) for help."


class AssistantOutcomeKind(StrEnum):
    ANSWERED = "answered"
    ABSTAINED = "abstained"
    ESCALATED = "escalated"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class GroundedAnswer:
    """A grounded-answer result, self-sufficient without the enclosing ``AssistantOutcome``."""

    kind: AssistantOutcomeKind
    status: AnswerStatus
    answer_text: str | None
    citations: tuple[str, ...]
    clarifying_question: str | None
    retrieved_ids: tuple[str, ...]

    @property
    def needs_clarification(self) -> bool:
        return self.clarifying_question is not None


@dataclass(frozen=True, slots=True)
class AssistantFailure:
    """Why the assistant could not produce a grounded answer. Never carries model prose."""

    violation_kind: ViolationKind | None
    error_kind: ProviderErrorKind | None
    detail: str | None


@dataclass(frozen=True, slots=True)
class AssistantOutcome:
    kind: AssistantOutcomeKind
    answer: GroundedAnswer | None
    guidance: str
    failure: AssistantFailure | None


def _no_evidence_outcome() -> AssistantOutcome:
    answer = GroundedAnswer(
        kind=AssistantOutcomeKind.ABSTAINED,
        status=AnswerStatus.ABSTAINED,
        answer_text=None,
        citations=(),
        clarifying_question=None,
        retrieved_ids=(),
    )
    return AssistantOutcome(
        kind=AssistantOutcomeKind.ABSTAINED,
        answer=answer,
        guidance=_REFERRAL_GUIDANCE,
        failure=None,
    )


def answer_for_actor(
    question: str,
    *,
    manifest: DemoAccessManifest,
    actor_id: Identifier,
    access_map: DocumentAccessMap,
    provider: AnswerProvider,
    model: ModelConfig,
    prompt: PromptTemplate | None = None,
    k: int = DEFAULT_K,
) -> AssistantOutcome:
    """Resolve ``actor_id`` itself, then map ``answer_question``'s result onto a typed outcome.

    Never accepts a ``DemoIdentity``: only a server-selected ``actor_id`` reaches retrieval and
    the model prompt, so a forged/hand-built identity has no way into this path.
    """
    identity = resolve_identity(manifest, actor_id)
    pipeline = answer_question(
        question,
        identity=identity,
        access_map=access_map,
        provider=provider,
        model=model,
        prompt=prompt,
        k=k,
    )

    status = pipeline.answer.status if pipeline.answer is not None else None

    match (pipeline.kind, status):
        case (OutcomeKind.NO_EVIDENCE, None):
            return _no_evidence_outcome()

        case (OutcomeKind.ANSWER, AnswerStatus.ANSWERED):
            assert pipeline.answer is not None
            answer = GroundedAnswer(
                kind=AssistantOutcomeKind.ANSWERED,
                status=AnswerStatus.ANSWERED,
                answer_text=pipeline.answer.answer_text,
                citations=pipeline.answer.citations,
                clarifying_question=pipeline.answer.clarifying_question,
                retrieved_ids=pipeline.retrieved_ids,
            )
            return AssistantOutcome(
                kind=AssistantOutcomeKind.ANSWERED,
                answer=answer,
                guidance=_ANSWERED_GUIDANCE,
                failure=None,
            )

        case (OutcomeKind.ANSWER, AnswerStatus.ESCALATED):
            assert pipeline.answer is not None
            answer = GroundedAnswer(
                kind=AssistantOutcomeKind.ESCALATED,
                status=AnswerStatus.ESCALATED,
                answer_text=pipeline.answer.answer_text,
                citations=pipeline.answer.citations,
                clarifying_question=pipeline.answer.clarifying_question,
                retrieved_ids=pipeline.retrieved_ids,
            )
            return AssistantOutcome(
                kind=AssistantOutcomeKind.ESCALATED,
                answer=answer,
                guidance=_REFERRAL_GUIDANCE,
                failure=None,
            )

        case (OutcomeKind.ANSWER, AnswerStatus.ABSTAINED):
            assert pipeline.answer is not None
            answer = GroundedAnswer(
                kind=AssistantOutcomeKind.ABSTAINED,
                status=AnswerStatus.ABSTAINED,
                answer_text=None,
                citations=pipeline.answer.citations,
                clarifying_question=None,
                retrieved_ids=pipeline.retrieved_ids,
            )
            return AssistantOutcome(
                kind=AssistantOutcomeKind.ABSTAINED,
                answer=answer,
                guidance=_REFERRAL_GUIDANCE,
                failure=None,
            )

        case (OutcomeKind.CONTRACT_VIOLATION, None):
            failure = AssistantFailure(
                violation_kind=pipeline.violation_kind,
                error_kind=None,
                detail=pipeline.detail,
            )
            return AssistantOutcome(
                kind=AssistantOutcomeKind.UNAVAILABLE,
                answer=None,
                guidance=_UNAVAILABLE_GUIDANCE,
                failure=failure,
            )

        case (OutcomeKind.PROVIDER_ERROR, None):
            failure = AssistantFailure(
                violation_kind=None,
                error_kind=pipeline.error_kind,
                detail=pipeline.detail,
            )
            return AssistantOutcome(
                kind=AssistantOutcomeKind.UNAVAILABLE,
                answer=None,
                guidance=_UNAVAILABLE_GUIDANCE,
                failure=failure,
            )

        case _:
            raise AssertionError(
                f"unmapped pipeline outcome: kind={pipeline.kind!r}, status={status!r}"
            )


def create_draft_from_fields(
    payload: LeaveRequestPayload,
    *,
    repository: SQLiteLeaveRepository,
    manifest: DemoAccessManifest,
    actor_id: Identifier,
    request_id: Identifier,
    idempotency_key: IdempotencyKey,
    event_id: str,
    occurred_at: datetime,
) -> LeaveRequestPreview:
    """Create a draft from an already-typed payload and return its confirmable preview.

    Pure plumbing (D-D): ``request_id``, ``idempotency_key``, ``event_id``, ``occurred_at`` and
    ``actor_id`` are all caller/server supplied, never derived from question text or model
    output, and ``payload`` is not parsed, coerced, or defaulted here.
    """
    command_input = CreateDraftInput(idempotency_key=idempotency_key, payload=payload)
    command = bind_server_command(
        manifest, actor_id, command_input, generated_request_id=request_id
    )
    request = repository.execute(manifest, command, event_id=event_id, occurred_at=occurred_at)
    return build_leave_preview(request)


def provide_clarification_from_fields(
    payload: LeaveRequestPayload,
    *,
    repository: SQLiteLeaveRepository,
    manifest: DemoAccessManifest,
    actor_id: Identifier,
    request_id: Identifier,
    expected_version: int,
    idempotency_key: IdempotencyKey,
    event_id: str,
    occurred_at: datetime,
) -> LeaveRequestPreview:
    """Answer a clarification request with an already-typed payload and re-preview it.

    The state machine already routes ``NEEDS_CLARIFICATION -> NEEDS_CLARIFICATION`` for this
    command; this function only composes the command and re-previews the result. Same
    server-supplied invariant as ``create_draft_from_fields``.
    """
    command_input = ProvideClarificationInput(
        idempotency_key=idempotency_key,
        request_id=request_id,
        expected_version=expected_version,
        payload=payload,
    )
    command = bind_server_command(manifest, actor_id, command_input)
    request = repository.execute(manifest, command, event_id=event_id, occurred_at=occurred_at)
    return build_leave_preview(request)


def build_clarification_request(
    answer: GroundedAnswer,
    *,
    request_id: Identifier,
    expected_version: int,
    idempotency_key: IdempotencyKey,
) -> RequestClarificationInput:
    """Build a ``RequestClarificationInput`` from a grounded answer's own clarifying question.

    Input only (D-D): authorization happens later, in ``bind_server_command``/
    ``repository.execute``. This function never checks the actor's role — that policy already
    lives in ``access_policy``/``COMMAND_SPECS`` and duplicating it here would be a defect, not
    a style choice. ``request_id``, ``expected_version`` and ``idempotency_key`` are
    caller/server-supplied, never derived, same as every other builder in this module.
    """
    # Task 3's answer_for_actor produces ABSTAINED two different ways (synthesized no-evidence,
    # and the model's own AnswerStatus.ABSTAINED); this single kind check rejects both
    # uniformly, with nothing left to special-case.
    if answer.kind in (AssistantOutcomeKind.UNAVAILABLE, AssistantOutcomeKind.ABSTAINED):
        raise WorkflowError(WorkflowErrorCode.VALIDATION_FAILED)

    if not answer.citations:
        raise WorkflowError(WorkflowErrorCode.VALIDATION_FAILED)

    if answer.clarifying_question is None or not answer.clarifying_question.strip():
        raise WorkflowError(WorkflowErrorCode.VALIDATION_FAILED)

    # Code-built suffix: only document ids, never retrieved document text or other model output.
    suffix = f" (source: {', '.join(answer.citations)})"

    # Same whitespace collapsing as RequestClarificationInput.normalize_question, since our
    # composed string must already satisfy that validator before construction.
    normalized_question = " ".join(answer.clarifying_question.split())

    # Decision: truncate the clarifying-question portion to fit max_length=500, always keeping
    # the full source suffix intact so the citation is never silently dropped.
    available = _QUESTION_MAX_LENGTH - len(suffix)
    if available < 1:
        raise WorkflowError(WorkflowErrorCode.VALIDATION_FAILED)
    if len(normalized_question) > available:
        normalized_question = normalized_question[:available].rstrip()

    question = normalized_question + suffix

    try:
        return RequestClarificationInput(
            request_id=request_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            question=question,
        )
    except ValidationError as error:
        # A raw ValidationError must never escape this module (untyped; the caller cannot
        # handle it the way it handles every other outcome here).
        raise WorkflowError(WorkflowErrorCode.VALIDATION_FAILED) from error
