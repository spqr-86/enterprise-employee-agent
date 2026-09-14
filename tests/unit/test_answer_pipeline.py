from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from enterprise_employee_agent.knowledge.access import (
    DocumentAccessMap,
    DocumentVisibility,
    KnowledgeDocument,
)
from enterprise_employee_agent.knowledge.answer import (
    OutcomeKind,
    answer_question,
    load_prompt,
    render_user_prompt,
)
from enterprise_employee_agent.knowledge.retrieval import RetrievedDocument
from enterprise_employee_agent.leave.contracts import ActorRole
from enterprise_employee_agent.llm.contract import AnswerStatus, ViolationKind
from enterprise_employee_agent.llm.openrouter import OpenRouterProvider
from enterprise_employee_agent.llm.provider import AnswerRequest, ModelConfig, ProviderErrorKind
from enterprise_employee_agent.llm.scripted import ScriptedProvider

FIXTURES = Path("tests/fixtures/llm")
US = "people-policies/leave-of-absence/us.md"
SECRET_MARKER = "RESTRICTED-MARKER-7731"
MODEL = ModelConfig(model_id="test/model", max_tokens=100, timeout_seconds=5.0)
QUESTION = "How many weeks of parental leave are paid?"
ANSWERED_CONTRACT_CONTENT = json.loads(
    (FIXTURES / "openrouter-answered.json").read_text(encoding="utf-8")
)["choices"][0]["message"]["content"]


def _access_map() -> DocumentAccessMap:
    return DocumentAccessMap(
        access_version="t",
        corpus_version="t",
        documents=(
            KnowledgeDocument(
                US, "Parental leave is 16 weeks and paid.", DocumentVisibility.PUBLIC
            ),
            KnowledgeDocument(
                "synthetic/secret",
                f"How many weeks of parental leave are paid? {SECRET_MARKER}",
                DocumentVisibility.HR_ONLY,
            ),
        ),
    )


def _fixture_provider(name: str) -> OpenRouterProvider:
    body = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body)))
    return OpenRouterProvider("sk-test", client=client)


def _run(provider, **kwargs):  # type: ignore[no-untyped-def]
    return answer_question(
        QUESTION,
        role=ActorRole.EMPLOYEE,
        access_map=_access_map(),
        provider=provider,
        model=MODEL,
        **kwargs,
    )


def test_prompt_loads_with_stable_hash() -> None:
    prompt = load_prompt()
    assert prompt.version == "answer-v1"
    assert "untrusted data" in prompt.system
    assert "{documents}" in prompt.user and "{question}" in prompt.user
    assert len(prompt.sha256) == 64
    assert prompt.sha256 == load_prompt().sha256


def test_user_prompt_substitutes_in_a_single_pass() -> None:
    retrieved = [RetrievedDocument(document_id=US, score=1, text="text with {question} inside")]
    rendered = render_user_prompt(load_prompt(), "asks about {documents}", retrieved)
    assert f'<document id="{US}">' in rendered
    assert "text with {question} inside" in rendered
    assert "asks about {documents}" in rendered


def test_zero_overlap_abstains_without_calling_the_provider() -> None:
    provider = ScriptedProvider({})
    outcome = answer_question(
        "Germany Kindergeld",
        role=ActorRole.EMPLOYEE,
        access_map=_access_map(),
        provider=provider,
        model=MODEL,
    )
    assert outcome.kind is OutcomeKind.NO_EVIDENCE
    assert outcome.abstained is True
    assert provider.requests == []


@pytest.mark.parametrize(
    ("fixture", "status"),
    [
        ("openrouter-answered.json", AnswerStatus.ANSWERED),
        ("openrouter-abstained.json", AnswerStatus.ABSTAINED),
        ("openrouter-escalated.json", AnswerStatus.ESCALATED),
    ],
)
def test_valid_answers_pass_through(fixture: str, status: AnswerStatus) -> None:
    outcome = _run(_fixture_provider(fixture))
    assert outcome.kind is OutcomeKind.ANSWER
    assert outcome.answer is not None and outcome.answer.status is status
    assert outcome.retrieved_ids == (US,)
    assert outcome.abstained is (status is AnswerStatus.ABSTAINED)


@pytest.mark.parametrize(
    ("fixture", "kind"),
    [
        ("openrouter-malformed-content.json", ViolationKind.INVALID_JSON),
        ("openrouter-citation-outside.json", ViolationKind.CITATION_NOT_RETRIEVED),
    ],
)
def test_contract_violations_are_recorded(fixture: str, kind: ViolationKind) -> None:
    outcome = _run(_fixture_provider(fixture))
    assert outcome.kind is OutcomeKind.CONTRACT_VIOLATION
    assert outcome.violation_kind is kind
    assert outcome.response is not None
    assert outcome.abstained is False
    assert outcome.citations == ()


def test_provider_timeout_is_recorded_as_provider_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated", request=request)

    provider = OpenRouterProvider(
        "sk-test", client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    outcome = _run(provider)
    assert outcome.kind is OutcomeKind.PROVIDER_ERROR
    assert outcome.error_kind is ProviderErrorKind.TIMEOUT
    assert outcome.request_record is not None


def test_restricted_document_never_reaches_model_context_for_employee() -> None:
    provider = ScriptedProvider({QUESTION: ANSWERED_CONTRACT_CONTENT})
    outcome = _run(provider)
    assert outcome.kind is OutcomeKind.ANSWER
    assert provider.requests, "the provider must have been called with the public document"
    request = provider.requests[0]
    assert SECRET_MARKER not in request.user_prompt
    assert request.retrieved_ids == (US,)


def test_before_call_can_stop_the_call() -> None:
    provider = ScriptedProvider({})

    def refuse(request: AnswerRequest) -> None:
        raise RuntimeError("budget")

    with pytest.raises(RuntimeError, match="budget"):
        _run(provider, before_call=refuse)
    assert provider.requests == []
