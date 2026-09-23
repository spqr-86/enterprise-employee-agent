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
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx

from enterprise_employee_agent.evals.live import DECISION_MODEL
from enterprise_employee_agent.knowledge.access import DocumentAccessMap, load_document_access_map
from enterprise_employee_agent.knowledge.corpus import DATA_DIR, load_manifest
from enterprise_employee_agent.leave.access_policy import resolve_identity
from enterprise_employee_agent.leave.contracts import (
    ActorRole,
    DemoAccessManifest,
    DemoIdentity,
    load_demo_access_manifest,
)
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


@dataclass(frozen=True, slots=True)
class CitationInfo:
    """Display metadata for one cited document; ``source_url`` is None for synthetic fixtures."""

    document_id: str
    title: str
    source_url: str | None
    excerpt: str


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
