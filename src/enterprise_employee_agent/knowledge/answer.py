"""Answer pipeline: role-filtered retrieval → versioned prompt → provider → validated contract.

Retrieved document text and the question are untrusted and are wrapped in tags. Zero retrieved
documents means abstention without a model call. Provider failures and contract violations are
returned as outcomes, never raised. Exceptions from ``before_call`` (the budget guard) propagate.
"""

# ANCHOR: The single entry point that turns a question into a PipelineOutcome for Issue #8
# (Task 5). It composes Task 1 authorization, Task 2 retrieval, the versioned prompt in
# prompts/answer-v1/, Task 4's provider-neutral AnswerProvider, and Task 3's contract parsing.
# Task 7 (offline eval) and Task 10 (live CLI) call answer_question() and never touch a
# provider SDK directly.

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from importlib import resources

from enterprise_employee_agent.knowledge.access import DocumentAccessMap
from enterprise_employee_agent.knowledge.retrieval import DEFAULT_K, RetrievedDocument, retrieve
from enterprise_employee_agent.leave.contracts import ActorRole
from enterprise_employee_agent.llm.contract import (
    AnswerContract,
    AnswerStatus,
    ContractViolation,
    ViolationKind,
    parse_answer,
)
from enterprise_employee_agent.llm.provider import (
    AnswerProvider,
    AnswerRequest,
    ModelConfig,
    ProviderError,
    ProviderErrorKind,
    ProviderResponse,
)

PROMPT_VERSION = "answer-v1"
_PROMPT_PACKAGE = "enterprise_employee_agent.prompts"
_PLACEHOLDER = re.compile(r"\{(documents|question)\}")


@dataclass(frozen=True, slots=True)
class PromptTemplate:
    version: str
    system: str
    user: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(
            self.system.encode("utf-8") + b"\0" + self.user.encode("utf-8")
        ).hexdigest()


def load_prompt(version: str = PROMPT_VERSION) -> PromptTemplate:
    root = resources.files(_PROMPT_PACKAGE).joinpath(version)
    return PromptTemplate(
        version=version,
        system=root.joinpath("system.md").read_text(encoding="utf-8"),
        user=root.joinpath("user.md").read_text(encoding="utf-8"),
    )


def render_user_prompt(
    prompt: PromptTemplate, question: str, retrieved: Sequence[RetrievedDocument]
) -> str:
    documents = "\n".join(
        f'<document id="{item.document_id}">\n{item.text}\n</document>' for item in retrieved
    )
    values = {"documents": documents, "question": question}
    return _PLACEHOLDER.sub(lambda match: values[match.group(1)], prompt.user)


class OutcomeKind(StrEnum):
    ANSWER = "answer"
    NO_EVIDENCE = "no_evidence"
    CONTRACT_VIOLATION = "contract_violation"
    PROVIDER_ERROR = "provider_error"


@dataclass(frozen=True, slots=True)
class PipelineOutcome:
    kind: OutcomeKind
    retrieved_ids: tuple[str, ...]
    request_record: Mapping[str, object] | None = None
    response: ProviderResponse | None = None
    answer: AnswerContract | None = None
    violation_kind: ViolationKind | None = None
    error_kind: ProviderErrorKind | None = None
    detail: str | None = None

    @property
    def abstained(self) -> bool:
        if self.kind is OutcomeKind.NO_EVIDENCE:
            return True
        return self.answer is not None and self.answer.status is AnswerStatus.ABSTAINED

    @property
    def citations(self) -> tuple[str, ...]:
        return self.answer.citations if self.answer is not None else ()


def answer_question(
    question: str,
    *,
    role: ActorRole,
    access_map: DocumentAccessMap,
    provider: AnswerProvider,
    model: ModelConfig,
    prompt: PromptTemplate | None = None,
    k: int = DEFAULT_K,
    before_call: Callable[[AnswerRequest], None] | None = None,
) -> PipelineOutcome:
    prompt = prompt if prompt is not None else load_prompt()
    retrieved = retrieve(question, role, access_map, k=k)
    retrieved_ids = tuple(item.document_id for item in retrieved)
    if not retrieved:
        return PipelineOutcome(kind=OutcomeKind.NO_EVIDENCE, retrieved_ids=())

    request = AnswerRequest(
        model=model,
        system_prompt=prompt.system,
        user_prompt=render_user_prompt(prompt, question, retrieved),
        question=question,
        retrieved_ids=retrieved_ids,
    )
    if before_call is not None:
        before_call(request)
    try:
        response = provider.complete(request)
    except ProviderError as error:
        return PipelineOutcome(
            kind=OutcomeKind.PROVIDER_ERROR,
            retrieved_ids=retrieved_ids,
            request_record=request.record(),
            error_kind=error.kind,
            detail=error.detail,
        )
    try:
        answer = parse_answer(response.content, retrieved_ids)
    except ContractViolation as violation:
        return PipelineOutcome(
            kind=OutcomeKind.CONTRACT_VIOLATION,
            retrieved_ids=retrieved_ids,
            request_record=request.record(),
            response=response,
            violation_kind=violation.kind,
            detail=violation.detail,
        )
    return PipelineOutcome(
        kind=OutcomeKind.ANSWER,
        retrieved_ids=retrieved_ids,
        request_record=request.record(),
        response=response,
        answer=answer,
    )
