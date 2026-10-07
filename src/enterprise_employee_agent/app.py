"""Composition root and application service for the v0.1 demo UI (Issue #14).

``build_demo_application`` wires the frozen corpus, the synthetic identity manifest, SQLite
storage, and the model provider once. ``DemoApplication`` is the only object ``web/`` talks to.
"""

# ANCHOR: The seam between HTTP and the leave domain. No DemoApplication method accepts a
# DemoIdentity: each takes the cookie's actor_id and resolves it itself. Request ids, event ids,
# and timestamps are generated here, never read from a form. Every read of a stored request goes
# through can_view/project_for (or build_leave_preview after can_view), so a full LeaveRequest
# never reaches web/. sqlite3.Error becomes STORAGE_UNAVAILABLE and a pydantic ValidationError on
# client input becomes VALIDATION_FAILED, so only WorkflowError escapes. Live mode
# (OPENROUTER_API_KEY set) has no budget guard — a documented v0.1 limitation.

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
from pydantic import ValidationError

from enterprise_employee_agent.evals.live import DECISION_MODEL
from enterprise_employee_agent.knowledge.access import DocumentAccessMap, load_document_access_map
from enterprise_employee_agent.knowledge.corpus import DATA_DIR, load_manifest
from enterprise_employee_agent.leave.access_policy import (
    LeaveProjection,
    can_view,
    project_for,
    resolve_identity,
    visible_requests,
)
from enterprise_employee_agent.leave.assistant import (
    AssistantOutcome,
    FieldProposalOutcome,
    answer_for_actor,
    create_draft_from_fields,
    propose_leave_fields,
    provide_clarification_from_fields,
)
from enterprise_employee_agent.leave.contracts import (
    COMMAND_SPECS,
    IDENTIFIER_ADAPTER,
    ActorRole,
    CancelDraftInput,
    ClientCommandInput,
    CommandName,
    ConfirmationEnvelope,
    ConfirmSubmitInput,
    DemoAccessManifest,
    DemoIdentity,
    LeaveRequest,
    LeaveRequestPayload,
    LeaveRequestPreview,
    LeaveStatus,
    RequestClarificationInput,
    StartProcessingInput,
    UpdateDraftInput,
    WorkflowError,
    WorkflowErrorCode,
    bind_server_command,
    build_leave_preview,
    load_demo_access_manifest,
)
from enterprise_employee_agent.leave.state_machine import transition_target
from enterprise_employee_agent.llm.openrouter import OpenRouterProvider
from enterprise_employee_agent.llm.provider import (
    AnswerProvider,
    AnswerRequest,
    ModelConfig,
    ProviderError,
    ProviderErrorKind,
    ProviderResponse,
)
from enterprise_employee_agent.llm.scripted import ScriptedProvider
from enterprise_employee_agent.storage.sqlite import SQLiteLeaveRepository

DEMO_ACCESS_PATH = DATA_DIR / "synthetic_protected" / "demo-access-v1.json"
SCRIPTED_FIXTURE_PATH = DATA_DIR / "demo" / "scripted-v1.json"
DEFAULT_DATABASE_PATH = Path("var/demo.sqlite")
OFFLINE_MODEL = ModelConfig(model_id="offline/scripted", max_tokens=1, timeout_seconds=1.0)
EXCERPT_CHARS = 800
# Server-side mirrors of the HTML maxlength attributes on ask.html and request_new.html: the
# templates cap input for UX, but only these checks stop an over-limit call from reaching the
# model (m4, final review).
QUESTION_MAX_LENGTH = 1000
LEAVE_DESCRIPTION_MAX_LENGTH = 1000

type Clock = Callable[[], datetime]
type IdFactory = Callable[[str], str]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


@dataclass(frozen=True, slots=True)
class DemoSettings:
    database_path: Path
    openrouter_api_key: str | None

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> DemoSettings:
        env = os.environ if environ is None else environ
        return cls(
            database_path=Path(env.get("DEMO_DATABASE_PATH") or DEFAULT_DATABASE_PATH),
            openrouter_api_key=env.get("OPENROUTER_API_KEY") or None,
        )


@dataclass(frozen=True, slots=True)
class DemoMode:
    live: bool
    model_id: str

    @property
    def label(self) -> str:
        return f"live · {self.model_id}" if self.live else "offline · scripted"


@dataclass(frozen=True, slots=True)
class IdentityOption:
    identity_id: str
    display_name: str
    role: ActorRole
    can_create_request: bool


@dataclass(frozen=True, slots=True)
class CitationInfo:
    """Display metadata for one cited document; ``source_url`` is None for synthetic fixtures."""

    document_id: str
    title: str
    source_url: str | None
    excerpt: str


@dataclass(frozen=True, slots=True)
class LeaveForm:
    """Raw leave form strings; the domain payload validates them, never the web layer."""

    start_date: str
    end_date: str
    request_type: str
    employee_comment: str = ""

    def to_payload(self) -> LeaveRequestPayload:
        try:
            return LeaveRequestPayload(
                start_date=self.start_date,
                end_date=self.end_date,
                request_type=self.request_type,
                employee_comment=self.employee_comment or None,
            )
        except ValidationError as error:
            raise WorkflowError(WorkflowErrorCode.VALIDATION_FAILED) from error


@dataclass(frozen=True, slots=True)
class RequestView:
    projection: LeaveProjection
    preview: LeaveRequestPreview | None
    actions: frozenset[CommandName]


@dataclass(frozen=True, slots=True)
class AskResult:
    outcome: AssistantOutcome
    citations: tuple[CitationInfo, ...]


# Statuses HR never lists: the request has not left the employee's hands (spec, HR page).
_HR_HIDDEN_STATUSES = frozenset({LeaveStatus.DRAFT, LeaveStatus.CANCELLED})


def _available_actions(actor: DemoIdentity, request: LeaveRequest) -> frozenset[CommandName]:
    """Commands this role has and the state machine accepts from the current status."""

    available: set[CommandName] = set()
    for command in CommandName:
        if command is CommandName.CREATE_DRAFT:
            continue
        if actor.role not in COMMAND_SPECS[command].allowed_roles:
            continue
        try:
            transition_target(request, command)
        except WorkflowError:
            continue
        available.add(command)
    return frozenset(available)


@dataclass(frozen=True, slots=True)
class ScriptedFixture:
    responses: Mapping[str, str]
    questions: tuple[str, ...]
    leave_descriptions: tuple[str, ...]


def load_scripted_fixture(path: Path = SCRIPTED_FIXTURE_PATH) -> ScriptedFixture:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("schema_version") != 1:
        raise ValueError(f"unsupported scripted fixture schema in {path}")
    entries = (*raw["questions"], *raw["leave_descriptions"])
    responses = {entry["text"]: json.dumps(entry["response"]) for entry in entries}
    if len(responses) != len(entries):
        raise ValueError(f"duplicate scripted text in {path}")
    return ScriptedFixture(
        responses=responses,
        questions=tuple(entry["text"] for entry in raw["questions"]),
        leave_descriptions=tuple(entry["text"] for entry in raw["leave_descriptions"]),
    )


class OfflineDemoProvider:
    """``ScriptedProvider`` whose missing script is a provider failure, not a crash."""

    def __init__(self, responses: Mapping[str, str]) -> None:
        self._scripted = ScriptedProvider(responses)

    def complete(self, request: AnswerRequest) -> ProviderResponse:
        try:
            return self._scripted.complete(request)
        except LookupError as error:
            raise ProviderError(
                ProviderErrorKind.MALFORMED_RESPONSE, "no scripted response"
            ) from error


def _option(identity: DemoIdentity) -> IdentityOption:
    return IdentityOption(
        identity_id=identity.identity_id,
        display_name=identity.display_name,
        role=identity.role,
        can_create_request=identity.role in COMMAND_SPECS[CommandName.CREATE_DRAFT].allowed_roles,
    )


def _citation_index(access_map: DocumentAccessMap) -> dict[str, CitationInfo]:
    handbook = {document.id: document for document in load_manifest().documents}
    index: dict[str, CitationInfo] = {}
    for document in access_map.documents:
        entry = handbook.get(document.id)
        index[document.id] = CitationInfo(
            document_id=document.id,
            title=entry.title if entry is not None else document.id,
            source_url=entry.source_url if entry is not None else None,
            excerpt=document.text[:EXCERPT_CHARS],
        )
    return index


class DemoApplication:
    """The only entry point for ``web/``. Every method takes a cookie ``actor_id`` first."""

    def __init__(
        self,
        *,
        manifest: DemoAccessManifest,
        access_map: DocumentAccessMap,
        repository: SQLiteLeaveRepository,
        provider: AnswerProvider,
        model: ModelConfig,
        mode: DemoMode,
        fixture: ScriptedFixture | None,
        clock: Clock,
        id_factory: IdFactory,
    ) -> None:
        self._manifest = manifest
        self._access_map = access_map
        self._repository = repository
        self._provider = provider
        self._model = model
        self._mode = mode
        self._fixture = fixture
        self._clock = clock
        self._id_factory = id_factory
        self._citations = _citation_index(access_map)

    def mode(self) -> DemoMode:
        return self._mode

    def identities(self) -> tuple[IdentityOption, ...]:
        return tuple(_option(identity) for identity in self._manifest.identities)

    def identity(self, actor_id: str) -> IdentityOption:
        return _option(self._actor(actor_id))

    def suggested_questions(self) -> tuple[str, ...]:
        return self._fixture.questions if self._fixture is not None else ()

    def suggested_leave_descriptions(self) -> tuple[str, ...]:
        return self._fixture.leave_descriptions if self._fixture is not None else ()

    def _actor(self, actor_id: str) -> DemoIdentity:
        return resolve_identity(self._manifest, actor_id)

    @contextmanager
    def _domain_errors(self) -> Iterator[None]:
        try:
            yield
        except sqlite3.Error as error:
            raise WorkflowError(WorkflowErrorCode.STORAGE_UNAVAILABLE) from error
        except ValidationError as error:
            raise WorkflowError(WorkflowErrorCode.VALIDATION_FAILED) from error

    @staticmethod
    def _request_id(value: str) -> str:
        try:
            return IDENTIFIER_ADAPTER.validate_python(value)
        except ValidationError as error:
            raise WorkflowError(WorkflowErrorCode.NOT_FOUND) from error

    def _execute(self, actor_id: str, command_input: ClientCommandInput) -> LeaveRequest:
        command = bind_server_command(self._manifest, actor_id, command_input)
        return self._repository.execute(
            self._manifest,
            command,
            event_id=self._id_factory("evt"),
            occurred_at=self._clock(),
        )

    def create_draft(
        self, actor_id: str, form: LeaveForm, idempotency_key: str
    ) -> LeaveRequestPreview:
        self._actor(actor_id)
        with self._domain_errors():
            return create_draft_from_fields(
                form.to_payload(),
                repository=self._repository,
                manifest=self._manifest,
                actor_id=actor_id,
                request_id=self._id_factory("leave"),
                idempotency_key=idempotency_key,
                event_id=self._id_factory("evt"),
                occurred_at=self._clock(),
            )

    def update_draft(
        self,
        actor_id: str,
        request_id: str,
        expected_version: int,
        form: LeaveForm,
        idempotency_key: str,
    ) -> LeaveRequestPreview:
        self._actor(actor_id)
        request_id = self._request_id(request_id)
        with self._domain_errors():
            updated = self._execute(
                actor_id,
                UpdateDraftInput(
                    idempotency_key=idempotency_key,
                    request_id=request_id,
                    expected_version=expected_version,
                    payload=form.to_payload(),
                ),
            )
            return build_leave_preview(updated)

    def cancel_draft(
        self, actor_id: str, request_id: str, expected_version: int, idempotency_key: str
    ) -> LeaveProjection:
        actor = self._actor(actor_id)
        request_id = self._request_id(request_id)
        with self._domain_errors():
            cancelled = self._execute(
                actor_id,
                CancelDraftInput(
                    idempotency_key=idempotency_key,
                    request_id=request_id,
                    expected_version=expected_version,
                ),
            )
        return project_for(self._manifest, actor, cancelled)

    def confirm(
        self,
        actor_id: str,
        request_id: str,
        expected_version: int,
        payload_digest: str,
        idempotency_key: str,
    ) -> LeaveProjection:
        actor = self._actor(actor_id)
        request_id = self._request_id(request_id)
        with self._domain_errors():
            submitted = self._execute(
                actor_id,
                ConfirmSubmitInput(
                    idempotency_key=idempotency_key,
                    request_id=request_id,
                    expected_version=expected_version,
                    confirmation=ConfirmationEnvelope(
                        request_id=request_id,
                        request_version=expected_version,
                        payload_digest=payload_digest,
                    ),
                ),
            )
        return project_for(self._manifest, actor, submitted)

    def hr_start(
        self, actor_id: str, request_id: str, expected_version: int, idempotency_key: str
    ) -> LeaveProjection:
        actor = self._actor(actor_id)
        request_id = self._request_id(request_id)
        with self._domain_errors():
            started = self._execute(
                actor_id,
                StartProcessingInput(
                    idempotency_key=idempotency_key,
                    request_id=request_id,
                    expected_version=expected_version,
                ),
            )
        return project_for(self._manifest, actor, started)

    def hr_clarify(
        self,
        actor_id: str,
        request_id: str,
        expected_version: int,
        question: str,
        idempotency_key: str,
    ) -> LeaveProjection:
        actor = self._actor(actor_id)
        request_id = self._request_id(request_id)
        with self._domain_errors():
            asked = self._execute(
                actor_id,
                RequestClarificationInput(
                    idempotency_key=idempotency_key,
                    request_id=request_id,
                    expected_version=expected_version,
                    question=question,
                ),
            )
        return project_for(self._manifest, actor, asked)

    def employee_clarify(
        self,
        actor_id: str,
        request_id: str,
        expected_version: int,
        form: LeaveForm,
        idempotency_key: str,
    ) -> LeaveRequestPreview:
        self._actor(actor_id)
        request_id = self._request_id(request_id)
        with self._domain_errors():
            return provide_clarification_from_fields(
                form.to_payload(),
                repository=self._repository,
                manifest=self._manifest,
                actor_id=actor_id,
                request_id=request_id,
                expected_version=expected_version,
                idempotency_key=idempotency_key,
                event_id=self._id_factory("evt"),
                occurred_at=self._clock(),
            )

    def request_for(self, actor_id: str, request_id: str) -> RequestView:
        actor = self._actor(actor_id)
        request_id = self._request_id(request_id)
        with self._domain_errors():
            request = self._repository.get(request_id)
        if request is None or not can_view(self._manifest, actor, request):
            raise WorkflowError(WorkflowErrorCode.NOT_FOUND)
        actions = _available_actions(actor, request)
        preview = build_leave_preview(request) if CommandName.CONFIRM_SUBMIT in actions else None
        return RequestView(
            projection=project_for(self._manifest, actor, request),
            preview=preview,
            actions=actions,
        )

    def ask(self, actor_id: str, question: str) -> AskResult:
        self._actor(actor_id)
        if len(question) > QUESTION_MAX_LENGTH:
            raise WorkflowError(WorkflowErrorCode.VALIDATION_FAILED)
        outcome = answer_for_actor(
            question,
            manifest=self._manifest,
            actor_id=actor_id,
            access_map=self._access_map,
            provider=self._provider,
            model=self._model,
        )
        cited = outcome.answer.citations if outcome.answer is not None else ()
        return AskResult(
            outcome=outcome,
            citations=tuple(self._citations[doc] for doc in cited if doc in self._citations),
        )

    def propose_fields(self, actor_id: str, text: str) -> FieldProposalOutcome:
        actor = self._actor(actor_id)
        if actor.role not in COMMAND_SPECS[CommandName.CREATE_DRAFT].allowed_roles:
            raise WorkflowError(WorkflowErrorCode.FORBIDDEN)
        if len(text) > LEAVE_DESCRIPTION_MAX_LENGTH:
            raise WorkflowError(WorkflowErrorCode.VALIDATION_FAILED)
        return propose_leave_fields(
            text,
            manifest=self._manifest,
            actor_id=actor_id,
            provider=self._provider,
            model=self._model,
        )

    def requests_for(self, actor_id: str) -> tuple[LeaveProjection, ...]:
        actor = self._actor(actor_id)
        with self._domain_errors():
            stored = self._repository.list_requests()
        visible = visible_requests(self._manifest, actor, stored)
        if actor.role is ActorRole.HR:
            visible = tuple(r for r in visible if r.status not in _HR_HIDDEN_STATUSES)
        return tuple(project_for(self._manifest, actor, request) for request in visible)


def build_demo_application(
    settings: DemoSettings,
    *,
    clock: Clock = _utc_now,
    id_factory: IdFactory = _new_id,
    provider: AnswerProvider | None = None,
) -> DemoApplication:
    """Compose the demo once.

    ``provider`` is a test seam: it replaces the offline script, keeps the offline mode, and
    shows no scripted suggestions. Without it, a non-empty API key selects live OpenRouter with
    ``DECISION_MODEL``; otherwise the offline script is used.
    """
    fixture: ScriptedFixture | None = None
    if provider is not None:
        model, mode = OFFLINE_MODEL, DemoMode(live=False, model_id=OFFLINE_MODEL.model_id)
    elif settings.openrouter_api_key:
        provider = OpenRouterProvider(settings.openrouter_api_key, client=httpx.Client())
        model, mode = DECISION_MODEL, DemoMode(live=True, model_id=DECISION_MODEL.model_id)
    else:
        fixture = load_scripted_fixture()
        provider = OfflineDemoProvider(fixture.responses)
        model, mode = OFFLINE_MODEL, DemoMode(live=False, model_id=OFFLINE_MODEL.model_id)
    return DemoApplication(
        manifest=load_demo_access_manifest(DEMO_ACCESS_PATH),
        access_map=load_document_access_map(),
        repository=SQLiteLeaveRepository(settings.database_path),
        provider=provider,
        model=model,
        mode=mode,
        fixture=fixture,
        clock=clock,
        id_factory=id_factory,
    )
