# Issue #14 Minimal Role-Aware Demo Interface Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user run the complete v0.1 scenario through the browser: grounded question, leave draft, versioned preview, explicit confirmation, HR processing, and clarification loop. The UI is server-rendered and always shows the selected identity, its role, the model mode, the evidence, the preview version, and the request status.

**Architecture:** `app.py` composes the domain once (manifest, access map, corpus metadata, SQLite, provider). `DemoApplication` is the only object `web/` calls: each method takes the cookie's `actor_id`, resolves it itself, and lets only `WorkflowError` escape. `web/` holds only FastAPI routes, Jinja2 templates, display dataclasses (`views.py`), and error mapping (`errors.py`). CSRF protection uses a `SameSite=Strict` cookie plus an Origin/Referer check (decision 0006).

**Tech Stack:** Python 3.12, FastAPI, Jinja2, uvicorn, python-multipart, pydantic 2, SQLite, pytest with `fastapi.testclient.TestClient`, ruff.

**Spec:** `docs/superpowers/specs/2026-09-22-issue-14-demo-ui-design.md` (approved by the owner on 2026-09-22). Decision: `docs/decisions/0006-v0.1-demo-ui-csrf.md`.

## Global Constraints

- Python `>=3.12,<3.14`; ruff line length 100, rules `E,F,I,UP`; `from __future__ import annotations` at the top of every module, as in the existing code.
- Commands: `uv run --locked pytest`, `uv run --locked ruff check .`, `uv run --locked ruff format --check .`, `uv run --locked pytest -m smoke`. Code blocks in this plan are not pre-formatted: run `uv run --locked ruff check --fix . && uv run --locked ruff format .` before each check step.
- Every automated test is offline. Tests never set `OPENROUTER_API_KEY` and never touch the network.
- `web/` contains no business rules and never resolves identities or checks roles itself. It calls `DemoApplication` only.
- `DemoApplication` methods never accept a `DemoIdentity`. `request_id`, `event_id`, and `occurred_at` are generated server-side. Hidden form fields carry only `idempotency_key`, `expected_version`, and `payload_digest`, never an actor id.
- `AssistantFailure.detail`, `error_kind`, `violation_kind`, provider status codes, and schema names never reach a template.
- Identity cookie: name `demo_identity`, `HttpOnly`, `SameSite=Strict`, `Path=/`, unsigned by design.
- Every POST passes `require_same_origin` before any `DemoApplication` call.
- Every mutating POST ends with `303`. `/ask` and `/requests/propose` render directly.
- Jinja2 autoescape stays on. Model and corpus text is never marked `|safe`.
- Server bind address: `127.0.0.1` only.
- Conventional English commits, one logical change each. Branch `feat/14-demo-ui`, one PR, squash merge after independent QA and owner acceptance.

## Deviations from the spec (owner-visible, decided while planning)

1. **`DemoSettings` has no `host`/`port`.** The `make demo` uvicorn flags set them, so settings fields would never be read.
2. **uvicorn uses a factory, not a module-level `app`.** `make demo` runs `enterprise_employee_agent.web.server:create_app_from_env --factory`. A module-level `app` would create `var/demo.sqlite` whenever a test imported `web.server`.
3. **`preview()` is folded into `request_for()`.** `RequestView.preview` is set whenever `confirm_submit` is an available action. HR audit history comes from `HrLeaveProjection.audit_history`, which `project_for` already returns HR-only. A separate `authorize_audit_history` call would repeat that guarantee.
4. **The HR list also hides `cancelled`.** `cancel_draft` is only allowed from `draft`, so a cancelled request never left draft. Opening a request by id still follows `can_view`.
5. **Web tests use the real `DemoApplication` instead of a fake.** It runs on a temporary SQLite database with the offline or an injected `ScriptedProvider`/failing provider. A fake would drift from the real class, and the real one is already fast and offline. `build_demo_application(..., provider=...)` is the test seam for this.
6. **Additions needed by the pages:**
   - `DemoApplication.identity(actor_id)`, `suggested_questions()`, and `suggested_leave_descriptions()`.
   - `RequestView.actions`: the actions available to the actor, computed from `COMMAND_SPECS` and `state_machine.transition_target`, so templates never decide what is allowed.
   - The clarification answer route is `POST /requests/{id}/clarification-response`.
7. **Added from `PLAN.md` §6 (Issue #10 finding carried to #14):** the repository now closes every SQLite connection after each call. The spec's domain section did not list this.

## File Structure

| Path | Responsibility |
|---|---|
| `src/enterprise_employee_agent/leave/contracts.py` (modify) | `WorkflowErrorCode.STORAGE_UNAVAILABLE` and its message |
| `src/enterprise_employee_agent/storage/sqlite.py` (modify) | `list_requests()`; one closed connection per call |
| `data/demo/scripted-v1.json` (create) | offline script: 3 questions, 1 leave description |
| `src/enterprise_employee_agent/app.py` (create) | `DemoSettings`, `DemoMode`, `OfflineDemoProvider`, `DemoApplication`, `build_demo_application` |
| `src/enterprise_employee_agent/web/__init__.py` (create) | package marker |
| `src/enterprise_employee_agent/web/session.py` (create) | identity cookie, Origin/Referer dependency |
| `src/enterprise_employee_agent/web/errors.py` (create) | error code → HTTP status, titles, generic messages |
| `src/enterprise_employee_agent/web/views.py` (create) | display dataclasses built from `DemoApplication` results |
| `src/enterprise_employee_agent/web/server.py` (create) | `create_app`, `create_app_from_env`, routes, exception handlers |
| `src/enterprise_employee_agent/web/templates/*.html` (create) | Jinja2 pages |
| `src/enterprise_employee_agent/web/static/demo.css` (create) | minimal CSS |
| `tests/unit/test_workflow_contracts.py`, `tests/integration/test_leave_sqlite_storage.py` (modify) | domain tests |
| `tests/unit/app/test_demo_composition.py`, `test_demo_workflow.py`, `test_demo_reads.py` (create) | `DemoApplication` |
| `tests/unit/web/test_web_foundation.py`, `test_web_requests.py` (create) | HTTP contracts |
| `tests/integration/test_demo_ui_journey.py` (create) | full journey through `TestClient` |
| `tests/smoke/test_demo_ui_smoke.py` (create) | offline start from environment |
| `pyproject.toml`, `uv.lock`, `Makefile`, `.gitignore` (modify) | dependencies, `make demo`, `var/` |

Test files in new directories have unique basenames and no `conftest.py`. Each test module keeps a small `_demo`/`_client` helper, following the existing duplication between `tests/smoke/conftest.py` and `tests/integration/conftest.py`.

---

### Task 0: Preflight and branch

- [ ] **Step 1: Verify the starting point**

Run: `git status -sb && git log --oneline -1 && uv run --locked pytest -q 2>&1 | tail -2`
Expected: `## main...origin/main` with a clean tree, head `373f79b` or later, all tests pass (366 at the time of writing).

- [ ] **Step 2: State the control line and move the Issue**

State: `Stage: in-progress. Required documents: read. Next allowed action: implement Issue #14 on feat/14-demo-ui. Merge: blocked until QA PASS and owner acceptance.`

```bash
git switch -c feat/14-demo-ui
gh issue edit 14 --remove-label ready --add-label in-progress
```

---

### Task 1: Storage safety for a live server

**Files:**
- Modify: `src/enterprise_employee_agent/leave/contracts.py` (`WorkflowErrorCode`, `ERROR_MESSAGES`)
- Modify: `src/enterprise_employee_agent/storage/sqlite.py`
- Test: `tests/unit/test_workflow_contracts.py`, `tests/integration/test_leave_sqlite_storage.py`

**Interfaces:**
- Produces: `WorkflowErrorCode.STORAGE_UNAVAILABLE` (value `"storage_unavailable"`); `SQLiteLeaveRepository.list_requests() -> tuple[LeaveRequest, ...]`, newest `updated_at` first, then `request_id` ascending; internal full records, so callers must authorize and project.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_workflow_contracts.py`:

```python
def test_storage_unavailable_has_a_safe_generic_message() -> None:
    assert WorkflowErrorCode.STORAGE_UNAVAILABLE.value == "storage_unavailable"
    assert ERROR_MESSAGES[WorkflowErrorCode.STORAGE_UNAVAILABLE] == (
        "The demo storage is unavailable; try again."
    )
```

Append to `tests/integration/test_leave_sqlite_storage.py` (it already imports `sqlite3`, `timedelta`, `CreateDraftInput`, `bind_server_command`, and defines `NOW`, `_payload`, and the `manifest`/`repository` fixtures):

```python
def _create_at(repository, manifest, *, actor_id, request_id, key, occurred_at):
    command = bind_server_command(
        manifest,
        actor_id,
        CreateDraftInput(idempotency_key=key, payload=_payload()),
        generated_request_id=request_id,
    )
    return repository.execute(
        manifest, command, event_id=f"event-{request_id}", occurred_at=occurred_at
    )


def test_list_requests_is_empty_for_a_new_database(repository) -> None:
    assert repository.list_requests() == ()


def test_list_requests_returns_full_records_newest_first(manifest, repository) -> None:
    older = _create_at(
        repository,
        manifest,
        actor_id="employee-alice",
        request_id="leave-list-001",
        key="list-alice-0001",
        occurred_at=NOW,
    )
    newer = _create_at(
        repository,
        manifest,
        actor_id="employee-carol",
        request_id="leave-list-002",
        key="list-carol-0001",
        occurred_at=NOW + timedelta(minutes=1),
    )

    assert repository.list_requests() == (newer, older)


def test_every_repository_call_closes_its_connection(tmp_path, monkeypatch, manifest) -> None:
    opened: list[sqlite3.Connection] = []
    real_connect = sqlite3.connect

    def tracking_connect(*args, **kwargs):
        connection = real_connect(*args, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", tracking_connect)
    repository = SQLiteLeaveRepository(tmp_path / "closing.db")
    repository.schema_version()
    repository.get("leave-missing")
    repository.list_requests()
    _create_at(
        repository,
        manifest,
        actor_id="employee-alice",
        request_id="leave-close-001",
        key="close-alice-0001",
        occurred_at=NOW,
    )

    assert len(opened) == 5
    for connection in opened:
        with pytest.raises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --locked pytest tests/unit/test_workflow_contracts.py tests/integration/test_leave_sqlite_storage.py -q`
Expected: FAIL. The failures should be `AttributeError: STORAGE_UNAVAILABLE`, `AttributeError: ... 'list_requests'`, and the closing test failing on the first open connection.

- [ ] **Step 3: Implement**

In `leave/contracts.py`, add the last member of `WorkflowErrorCode`:

```python
    STORAGE_UNAVAILABLE = "storage_unavailable"
```

and the last entry of `ERROR_MESSAGES`:

```python
    WorkflowErrorCode.STORAGE_UNAVAILABLE: "The demo storage is unavailable; try again.",
```

In `storage/sqlite.py`, add imports:

```python
from collections.abc import Iterator
from contextlib import contextmanager
```

Add this method under `_connect`:

```python
    @contextmanager
    def _session(self) -> Iterator[sqlite3.Connection]:
        """One connection per call: commit/rollback as before, then always close it."""

        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()
```

Replace each of the four `with self._connect() as connection:` lines (in `_migrate`, `schema_version`, `get`, `execute`) with `with self._session() as connection:`. Then add after `get`:

```python
    def list_requests(self) -> tuple[LeaveRequest, ...]:
        """Load every internal full record, newest first; callers must authorize and project."""

        with self._session() as connection:
            rows = connection.execute(
                "SELECT request_id FROM leave_requests ORDER BY updated_at DESC, request_id"
            ).fetchall()
            requests = tuple(self._get(connection, row["request_id"]) for row in rows)
        assert all(request is not None for request in requests)
        return requests  # type: ignore[return-value]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --locked pytest -q && uv run --locked ruff check . && uv run --locked ruff format --check .`
Expected: all tests pass, including the pre-existing crash-recovery and concurrency storage tests. Ruff reports no errors.

- [ ] **Step 5: Commit**

```bash
git add src/enterprise_employee_agent/leave/contracts.py src/enterprise_employee_agent/storage/sqlite.py tests/unit/test_workflow_contracts.py tests/integration/test_leave_sqlite_storage.py
git commit -m "feat: add storage-unavailable error, request listing, and closed connections"
```

---

### Task 2: Composition root and offline mode

**Files:**
- Create: `data/demo/scripted-v1.json`
- Create: `src/enterprise_employee_agent/app.py`
- Test: `tests/unit/app/test_demo_composition.py`

**Interfaces:**
- Consumes: `SQLiteLeaveRepository(path)`, `resolve_identity`, `load_demo_access_manifest`, `load_document_access_map`, `load_manifest`, `DECISION_MODEL`, `OpenRouterProvider`, `ScriptedProvider`, `answer_for_actor`.
- Produces:
  - `DemoSettings(database_path: Path, openrouter_api_key: str | None)` with `DemoSettings.from_env(environ: Mapping[str, str] | None = None)`
  - `DemoMode(live: bool, model_id: str)` with `.label`
  - `IdentityOption(identity_id, display_name, role: ActorRole)`
  - `CitationInfo(document_id, title, source_url: str | None, excerpt)`
  - `ScriptedFixture`, `load_scripted_fixture(path)`, `OfflineDemoProvider(responses)`
  - `DemoApplication` with `mode()`, `identities()`, `identity(actor_id)`, `suggested_questions()`, `suggested_leave_descriptions()`
  - `build_demo_application(settings, *, clock=..., id_factory=..., provider: AnswerProvider | None = None) -> DemoApplication`
  - Constants `OFFLINE_MODEL`, `DEMO_ACCESS_PATH`, `SCRIPTED_FIXTURE_PATH`

- [ ] **Step 1: Create the offline script**

`data/demo/scripted-v1.json`. The citations are the documents `retrieve_for_identity` returns at k=1 for each question, checked for employee and HR while planning. Every answer text restates only what the cited page says.

```json
{
  "schema_version": 1,
  "note": "Hand-written offline demo script for Issue #14. Not a recording of a real model.",
  "questions": [
    {
      "text": "How long is parental leave in the US?",
      "response": {
        "status": "answered",
        "answer_text": "The US leave page lists Parental Leave as 16 weeks, paid 100% by GitLab minus any State Disability and/or Paid Family Leave benefits.",
        "citations": ["people-policies/leave-of-absence/us.md"],
        "clarifying_question": null
      }
    },
    {
      "text": "What is a leave of absence?",
      "response": {
        "status": "answered",
        "answer_text": "The company-wide page describes leave as time away from work to recover from a serious health condition, care for a family member, bond with a new child, or serve in the military.",
        "citations": ["people-policies/leave-of-absence/_index.md"],
        "clarifying_question": null
      }
    },
    {
      "text": "Am I eligible for FMLA leave?",
      "response": {
        "status": "escalated",
        "answer_text": "The US page lists the FMLA requirements as 12 months of continuous service and 1250 hours worked in the year before the leave starts. The assistant cannot check your service or hours.",
        "citations": ["people-policies/leave-of-absence/us.md"],
        "clarifying_question": null
      }
    }
  ],
  "leave_descriptions": [
    {
      "text": "I need continuous leave from 2026-10-01 to 2026-10-05 for a family matter.",
      "response": {
        "start_date": "2026-10-01",
        "end_date": "2026-10-05",
        "request_type": "continuous",
        "employee_comment": "Family matter."
      }
    }
  ]
}
```

- [ ] **Step 2: Write the failing tests**

`tests/unit/app/test_demo_composition.py`:

```python
"""Composition, mode selection, identities, and the offline script (Issue #14)."""

from __future__ import annotations

import itertools
from datetime import UTC, datetime
from pathlib import Path

import pytest

from enterprise_employee_agent.app import (
    OFFLINE_MODEL,
    DemoApplication,
    DemoSettings,
    OfflineDemoProvider,
    build_demo_application,
    load_scripted_fixture,
)
from enterprise_employee_agent.evals.live import DECISION_MODEL
from enterprise_employee_agent.leave.access_policy import resolve_identity
from enterprise_employee_agent.leave.assistant import AssistantOutcomeKind, answer_for_actor
from enterprise_employee_agent.leave.contracts import (
    ActorRole,
    WorkflowError,
    WorkflowErrorCode,
    load_demo_access_manifest,
)
from enterprise_employee_agent.knowledge.access import load_document_access_map
from enterprise_employee_agent.llm.provider import (
    AnswerRequest,
    ModelConfig,
    ProviderError,
    ProviderErrorKind,
)

NOW = datetime(2026, 9, 21, 10, 0, tzinfo=UTC)
MANIFEST_PATH = Path("data/synthetic_protected/demo-access-v1.json")


def _demo(tmp_path: Path, *, api_key: str | None = None) -> DemoApplication:
    counter = itertools.count(1)
    return build_demo_application(
        DemoSettings(database_path=tmp_path / "demo.sqlite", openrouter_api_key=api_key),
        clock=lambda: NOW,
        id_factory=lambda prefix: f"{prefix}-{next(counter):04d}",
    )


def test_settings_from_env_defaults_to_offline_and_var_database() -> None:
    settings = DemoSettings.from_env({})
    assert settings.database_path == Path("var/demo.sqlite")
    assert settings.openrouter_api_key is None


def test_settings_from_env_reads_key_and_database_path() -> None:
    settings = DemoSettings.from_env(
        {"OPENROUTER_API_KEY": "sk-test", "DEMO_DATABASE_PATH": "/tmp/x.sqlite"}
    )
    assert settings.openrouter_api_key == "sk-test"
    assert settings.database_path == Path("/tmp/x.sqlite")


def test_empty_key_counts_as_unset() -> None:
    assert DemoSettings.from_env({"OPENROUTER_API_KEY": ""}).openrouter_api_key is None


def test_offline_mode_without_key(tmp_path) -> None:
    mode = _demo(tmp_path).mode()
    assert mode.live is False
    assert mode.label == "offline · scripted"


def test_live_mode_with_key_uses_the_decision_model(tmp_path) -> None:
    mode = _demo(tmp_path, api_key="sk-test-not-used").mode()
    assert mode.live is True
    assert mode.model_id == DECISION_MODEL.model_id
    assert mode.label == f"live · {DECISION_MODEL.model_id}"


def test_identities_list_all_six_manifest_identities(tmp_path) -> None:
    options = _demo(tmp_path).identities()
    assert [option.identity_id for option in options] == [
        "employee-alice",
        "employee-bob",
        "employee-carol",
        "manager-morgan",
        "manager-riley",
        "hr-harper",
    ]
    assert options[5].role is ActorRole.HR


def test_identity_resolves_known_and_rejects_unknown(tmp_path) -> None:
    demo = _demo(tmp_path)
    assert demo.identity("hr-harper").display_name == "Harper HR"
    for bad in ("employee-zed", "", "../etc"):
        with pytest.raises(WorkflowError) as error:
            demo.identity(bad)
        assert error.value.code is WorkflowErrorCode.UNAUTHORIZED


def test_offline_suggestions_come_from_the_script(tmp_path) -> None:
    demo = _demo(tmp_path)
    assert "How long is parental leave in the US?" in demo.suggested_questions()
    assert len(demo.suggested_leave_descriptions()) == 1


def test_live_mode_has_no_scripted_suggestions(tmp_path) -> None:
    demo = _demo(tmp_path, api_key="sk-test-not-used")
    assert demo.suggested_questions() == ()
    assert demo.suggested_leave_descriptions() == ()


def test_offline_provider_turns_a_missing_script_into_a_provider_error() -> None:
    provider = OfflineDemoProvider({})
    request = AnswerRequest(
        model=ModelConfig(model_id="m", max_tokens=1, timeout_seconds=1.0),
        system_prompt="s",
        user_prompt="u",
        question="unscripted",
        retrieved_ids=(),
    )
    with pytest.raises(ProviderError) as error:
        provider.complete(request)
    assert error.value.kind is ProviderErrorKind.MALFORMED_RESPONSE
    assert error.value.detail == "no scripted response"


@pytest.mark.parametrize("actor_id", ["employee-alice", "manager-morgan", "hr-harper"])
def test_every_scripted_question_is_grounded_for_every_role(actor_id) -> None:
    # Guards the fixture against retrieval drift: a citation outside the retrieved set would
    # turn the scripted answer into a contract violation (UNAVAILABLE).
    fixture = load_scripted_fixture()
    manifest = load_demo_access_manifest(MANIFEST_PATH)
    resolve_identity(manifest, actor_id)
    for question in fixture.questions:
        outcome = answer_for_actor(
            question,
            manifest=manifest,
            actor_id=actor_id,
            access_map=load_document_access_map(),
            provider=OfflineDemoProvider(fixture.responses),
            model=OFFLINE_MODEL,
        )
        assert outcome.kind in {AssistantOutcomeKind.ANSWERED, AssistantOutcomeKind.ESCALATED}
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run --locked pytest tests/unit/app/test_demo_composition.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'enterprise_employee_agent.app'`.

- [ ] **Step 4: Implement `app.py`**

`src/enterprise_employee_agent/app.py`:

```python
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
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run --locked pytest tests/unit/app/test_demo_composition.py -q && uv run --locked ruff check . && uv run --locked ruff format --check .`
Expected: PASS. If ruff's import sorter reorders the test imports, run `uv run --locked ruff check --fix . && uv run --locked ruff format .` and re-run.

- [ ] **Step 6: Commit**

```bash
git add data/demo/scripted-v1.json src/enterprise_employee_agent/app.py tests/unit/app/test_demo_composition.py
git commit -m "feat: compose the demo application with offline and live model modes"
```

---

### Task 3: `DemoApplication` workflow commands and request view

**Files:**
- Modify: `src/enterprise_employee_agent/app.py`
- Test: `tests/unit/app/test_demo_workflow.py`

**Interfaces:**
- Consumes: Task 2 `DemoApplication`/`build_demo_application`; Task 1 `STORAGE_UNAVAILABLE`; `create_draft_from_fields`, `provide_clarification_from_fields`, `bind_server_command`, `build_leave_preview`, `can_view`, `project_for`, `transition_target`.
- Produces:
  - `LeaveForm(start_date: str, end_date: str, request_type: str, employee_comment: str = "")` with `.to_payload() -> LeaveRequestPayload`. It raises `WorkflowError(VALIDATION_FAILED)`.
  - `RequestView(projection: LeaveProjection, preview: LeaveRequestPreview | None, actions: frozenset[CommandName])`
  - `create_draft(actor_id, form, idempotency_key) -> LeaveRequestPreview`
  - `update_draft(actor_id, request_id, expected_version, form, idempotency_key) -> LeaveRequestPreview`
  - `cancel_draft(actor_id, request_id, expected_version, idempotency_key) -> LeaveProjection`
  - `confirm(actor_id, request_id, expected_version, payload_digest, idempotency_key) -> LeaveProjection`
  - `hr_start(actor_id, request_id, expected_version, idempotency_key) -> LeaveProjection`
  - `hr_clarify(actor_id, request_id, expected_version, question, idempotency_key) -> LeaveProjection`
  - `employee_clarify(actor_id, request_id, expected_version, form, idempotency_key) -> LeaveRequestPreview`
  - `request_for(actor_id, request_id) -> RequestView`
  - Generated ids have the form `id_factory("leave")` and `id_factory("evt")`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/app/test_demo_workflow.py`:

```python
"""DemoApplication workflow commands and the single-request read path (Issue #14)."""

from __future__ import annotations

import itertools
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from enterprise_employee_agent.app import (
    DemoApplication,
    DemoSettings,
    LeaveForm,
    build_demo_application,
)
from enterprise_employee_agent.leave.contracts import (
    CommandName,
    EmployeeLeaveProjection,
    HrLeaveProjection,
    LeaveStatus,
    ManagerLeaveProjection,
    WorkflowError,
    WorkflowErrorCode,
)
from enterprise_employee_agent.storage.sqlite import SQLiteLeaveRepository

NOW = datetime(2026, 9, 21, 10, 0, tzinfo=UTC)
FORM = LeaveForm(
    start_date="2026-10-01",
    end_date="2026-10-05",
    request_type="continuous",
    employee_comment="Family matter.",
)


def _demo(tmp_path: Path) -> DemoApplication:
    counter = itertools.count(1)
    return build_demo_application(
        DemoSettings(database_path=tmp_path / "demo.sqlite", openrouter_api_key=None),
        clock=lambda: NOW,
        id_factory=lambda prefix: f"{prefix}-{next(counter):04d}",
    )


def _code(error: pytest.ExceptionInfo[WorkflowError]) -> WorkflowErrorCode:
    return error.value.code


def _submitted(demo: DemoApplication, actor_id: str = "employee-alice") -> str:
    preview = demo.create_draft(actor_id, FORM, f"create-{actor_id}")
    demo.confirm(
        actor_id,
        preview.request_id,
        preview.request_version,
        preview.confirmation.payload_digest,
        f"confirm-{actor_id}",
    )
    return preview.request_id


def test_create_draft_generates_ids_server_side_and_returns_version_one(tmp_path) -> None:
    preview = _demo(tmp_path).create_draft("employee-alice", FORM, "create-alice-01")
    assert preview.request_id == "leave-0001"
    assert preview.request_version == 1
    assert preview.payload.employee_comment == "Family matter."


def test_invalid_form_is_validation_failed(tmp_path) -> None:
    bad = LeaveForm(start_date="2026-10-05", end_date="2026-10-01", request_type="continuous")
    with pytest.raises(WorkflowError) as error:
        _demo(tmp_path).create_draft("employee-alice", bad, "create-alice-01")
    assert _code(error) is WorkflowErrorCode.VALIDATION_FAILED


def test_invalid_idempotency_key_is_validation_failed(tmp_path) -> None:
    with pytest.raises(WorkflowError) as error:
        _demo(tmp_path).create_draft("employee-alice", FORM, "short")
    assert _code(error) is WorkflowErrorCode.VALIDATION_FAILED


def test_unknown_actor_is_unauthorized_before_any_write(tmp_path) -> None:
    demo = _demo(tmp_path)
    with pytest.raises(WorkflowError) as error:
        demo.create_draft("employee-zed", FORM, "create-zed-0001")
    assert _code(error) is WorkflowErrorCode.UNAUTHORIZED


def test_manager_cannot_create_a_draft(tmp_path) -> None:
    with pytest.raises(WorkflowError) as error:
        _demo(tmp_path).create_draft("manager-morgan", FORM, "create-morgan-01")
    assert _code(error) is WorkflowErrorCode.FORBIDDEN


def test_employee_draft_view_has_preview_and_draft_actions(tmp_path) -> None:
    demo = _demo(tmp_path)
    preview = demo.create_draft("employee-alice", FORM, "create-alice-01")
    view = demo.request_for("employee-alice", preview.request_id)
    assert isinstance(view.projection, EmployeeLeaveProjection)
    assert view.preview == preview
    assert view.actions == {
        CommandName.UPDATE_DRAFT,
        CommandName.CANCEL_DRAFT,
        CommandName.CONFIRM_SUBMIT,
    }


def test_confirm_submits_and_hr_sees_processing_actions(tmp_path) -> None:
    demo = _demo(tmp_path)
    request_id = _submitted(demo)
    view = demo.request_for("hr-harper", request_id)
    assert isinstance(view.projection, HrLeaveProjection)
    assert view.projection.status is LeaveStatus.SUBMITTED
    assert len(view.projection.audit_history) == 2
    assert view.preview is None
    assert view.actions == {CommandName.START_PROCESSING, CommandName.REQUEST_CLARIFICATION}


def test_manager_sees_only_the_manager_projection_and_no_actions(tmp_path) -> None:
    demo = _demo(tmp_path)
    request_id = _submitted(demo)
    view = demo.request_for("manager-morgan", request_id)
    assert isinstance(view.projection, ManagerLeaveProjection)
    assert view.actions == frozenset()
    assert view.preview is None


def test_out_of_scope_and_missing_requests_look_the_same(tmp_path) -> None:
    demo = _demo(tmp_path)
    request_id = _submitted(demo)
    for actor_id, target in (
        ("manager-riley", request_id),
        ("employee-bob", request_id),
        ("employee-alice", "leave-9999"),
        ("employee-alice", "../not an id"),
    ):
        with pytest.raises(WorkflowError) as error:
            demo.request_for(actor_id, target)
        assert _code(error) is WorkflowErrorCode.NOT_FOUND


def test_update_then_old_confirmation_is_stale(tmp_path) -> None:
    demo = _demo(tmp_path)
    first = demo.create_draft("employee-alice", FORM, "create-alice-01")
    changed = LeaveForm(start_date="2026-10-01", end_date="2026-10-06", request_type="continuous")
    second = demo.update_draft("employee-alice", first.request_id, 1, changed, "update-alice-01")
    assert second.request_version == 2
    with pytest.raises(WorkflowError) as error:
        demo.confirm(
            "employee-alice",
            first.request_id,
            first.request_version,
            first.confirmation.payload_digest,
            "confirm-alice-01",
        )
    assert _code(error) is WorkflowErrorCode.STALE_CONFIRMATION


def test_cancel_draft_returns_cancelled_projection(tmp_path) -> None:
    demo = _demo(tmp_path)
    preview = demo.create_draft("employee-alice", FORM, "create-alice-01")
    projection = demo.cancel_draft("employee-alice", preview.request_id, 1, "cancel-alice-01")
    assert projection.status is LeaveStatus.CANCELLED


def test_clarification_round_trip(tmp_path) -> None:
    demo = _demo(tmp_path)
    request_id = _submitted(demo)
    asked = demo.hr_clarify("hr-harper", request_id, 2, "Confirm the end date.", "clarify-hr-01")
    assert asked.status is LeaveStatus.NEEDS_CLARIFICATION

    view = demo.request_for("employee-alice", request_id)
    assert view.projection.clarification_question == "Confirm the end date."
    assert CommandName.PROVIDE_CLARIFICATION in view.actions

    answered = demo.employee_clarify("employee-alice", request_id, 3, FORM, "answer-alice-01")
    assert answered.request_version == 4
    resubmitted = demo.confirm(
        "employee-alice",
        request_id,
        answered.request_version,
        answered.confirmation.payload_digest,
        "confirm-alice-02",
    )
    assert resubmitted.status is LeaveStatus.SUBMITTED
    started = demo.hr_start("hr-harper", request_id, 5, "start-hr-0001")
    assert started.status is LeaveStatus.PROCESSING


def test_blank_hr_question_is_validation_failed(tmp_path) -> None:
    demo = _demo(tmp_path)
    request_id = _submitted(demo)
    with pytest.raises(WorkflowError) as error:
        demo.hr_clarify("hr-harper", request_id, 2, "   ", "clarify-hr-01")
    assert _code(error) is WorkflowErrorCode.VALIDATION_FAILED


def test_employee_cannot_start_processing(tmp_path) -> None:
    demo = _demo(tmp_path)
    request_id = _submitted(demo)
    with pytest.raises(WorkflowError) as error:
        demo.hr_start("employee-alice", request_id, 2, "start-alice-01")
    assert _code(error) is WorkflowErrorCode.FORBIDDEN


def test_same_key_same_data_replays_and_different_data_conflicts(tmp_path) -> None:
    demo = _demo(tmp_path)
    first = demo.create_draft("employee-alice", FORM, "create-alice-01")
    again = demo.create_draft("employee-alice", FORM, "create-alice-01")
    assert again.request_id == first.request_id
    other = LeaveForm(start_date="2026-11-01", end_date="2026-11-02", request_type="intermittent")
    with pytest.raises(WorkflowError) as error:
        demo.create_draft("employee-alice", other, "create-alice-01")
    assert _code(error) is WorkflowErrorCode.IDEMPOTENCY_CONFLICT


def test_sqlite_errors_become_storage_unavailable(tmp_path, monkeypatch) -> None:
    demo = _demo(tmp_path)

    def broken(*args, **kwargs):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(SQLiteLeaveRepository, "execute", broken)
    monkeypatch.setattr(SQLiteLeaveRepository, "get", broken)
    with pytest.raises(WorkflowError) as error:
        demo.create_draft("employee-alice", FORM, "create-alice-01")
    assert _code(error) is WorkflowErrorCode.STORAGE_UNAVAILABLE
    with pytest.raises(WorkflowError) as error:
        demo.request_for("employee-alice", "leave-0001")
    assert _code(error) is WorkflowErrorCode.STORAGE_UNAVAILABLE
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --locked pytest tests/unit/app/test_demo_workflow.py -q`
Expected: FAIL with `ImportError: cannot import name 'LeaveForm'`.

- [ ] **Step 3: Implement**

In `app.py`, extend the imports. Add `import sqlite3`, `from collections.abc import Callable, Iterator, Mapping`, `from contextlib import contextmanager`, and `from pydantic import ValidationError`. Add the domain imports below. Keep the existing ones and let `ruff check --fix` sort them.

```python
from enterprise_employee_agent.leave.access_policy import (
    LeaveProjection,
    can_view,
    project_for,
    resolve_identity,
)
from enterprise_employee_agent.leave.assistant import (
    create_draft_from_fields,
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
```

Add after `CitationInfo`:

```python
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
```

Add these methods to `DemoApplication`, after `_actor`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --locked pytest tests/unit/app -q && uv run --locked ruff check . && uv run --locked ruff format --check .`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/enterprise_employee_agent/app.py tests/unit/app/test_demo_workflow.py
git commit -m "feat: expose leave workflow commands through the demo application"
```

---

### Task 4: `DemoApplication` questions, field proposals, and role lists

**Files:**
- Modify: `src/enterprise_employee_agent/app.py`
- Test: `tests/unit/app/test_demo_reads.py`

**Interfaces:**
- Consumes: Task 3 methods; `answer_for_actor`, `propose_leave_fields`, `visible_requests`, `SQLiteLeaveRepository.list_requests`.
- Produces:
  - `AskResult(outcome: AssistantOutcome, citations: tuple[CitationInfo, ...])`
  - `ask(actor_id, question) -> AskResult`
  - `propose_fields(actor_id, text) -> FieldProposalOutcome`
  - `requests_for(actor_id) -> tuple[LeaveProjection, ...]`. HR does not see `draft` or `cancelled` requests.

- [ ] **Step 1: Write the failing tests**

`tests/unit/app/test_demo_reads.py`:

```python
"""DemoApplication questions, field proposals, and role-scoped lists (Issue #14)."""

from __future__ import annotations

import itertools
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from enterprise_employee_agent.app import (
    DemoApplication,
    DemoSettings,
    LeaveForm,
    build_demo_application,
)
from enterprise_employee_agent.leave.assistant import (
    AssistantOutcomeKind,
    FieldProposalOutcomeKind,
)
from enterprise_employee_agent.leave.contracts import (
    HrLeaveProjection,
    ManagerLeaveProjection,
    WorkflowError,
    WorkflowErrorCode,
)
from enterprise_employee_agent.llm.provider import AnswerProvider
from enterprise_employee_agent.storage.sqlite import SQLiteLeaveRepository

NOW = datetime(2026, 9, 21, 10, 0, tzinfo=UTC)
US_DOC = "people-policies/leave-of-absence/us.md"
FORM = LeaveForm(start_date="2026-10-01", end_date="2026-10-05", request_type="continuous")


def _demo(tmp_path: Path, *, provider: AnswerProvider | None = None) -> DemoApplication:
    counter = itertools.count(1)
    return build_demo_application(
        DemoSettings(database_path=tmp_path / "demo.sqlite", openrouter_api_key=None),
        clock=lambda: NOW,
        id_factory=lambda prefix: f"{prefix}-{next(counter):04d}",
        provider=provider,
    )


def _submit(demo: DemoApplication, actor_id: str) -> str:
    preview = demo.create_draft(actor_id, FORM, f"create-{actor_id}")
    demo.confirm(
        actor_id,
        preview.request_id,
        1,
        preview.confirmation.payload_digest,
        f"confirm-{actor_id}",
    )
    return preview.request_id


def test_ask_scripted_question_returns_answer_with_citation_metadata(tmp_path) -> None:
    result = _demo(tmp_path).ask("employee-alice", "How long is parental leave in the US?")
    assert result.outcome.kind is AssistantOutcomeKind.ANSWERED
    assert [citation.document_id for citation in result.citations] == [US_DOC]
    citation = result.citations[0]
    assert citation.title == "United States Leave of Absence Policies"
    assert citation.source_url == (
        "https://handbook.gitlab.com/handbook/people-policies/leave-of-absence/us/"
    )
    assert citation.excerpt


def test_ask_unscripted_question_is_unavailable_not_a_crash(tmp_path) -> None:
    result = _demo(tmp_path).ask("employee-alice", "What is the weather today?")
    assert result.outcome.kind is AssistantOutcomeKind.UNAVAILABLE
    assert result.citations == ()


def test_ask_with_no_matching_evidence_abstains(tmp_path) -> None:
    result = _demo(tmp_path).ask("employee-alice", "zzqx")
    assert result.outcome.kind is AssistantOutcomeKind.ABSTAINED


def test_ask_rejects_unknown_actor(tmp_path) -> None:
    with pytest.raises(WorkflowError) as error:
        _demo(tmp_path).ask("nobody-here", "What is a leave of absence?")
    assert error.value.code is WorkflowErrorCode.UNAUTHORIZED


def test_propose_scripted_description(tmp_path) -> None:
    demo = _demo(tmp_path)
    outcome = demo.propose_fields("employee-alice", demo.suggested_leave_descriptions()[0])
    assert outcome.kind is FieldProposalOutcomeKind.PROPOSED
    assert outcome.proposal is not None
    assert outcome.proposal.missing_fields() == ()


def test_propose_unscripted_description_is_unavailable(tmp_path) -> None:
    outcome = _demo(tmp_path).propose_fields("employee-alice", "I need some time off.")
    assert outcome.kind is FieldProposalOutcomeKind.UNAVAILABLE
    assert outcome.proposal is None


def test_employee_list_contains_only_own_requests(tmp_path) -> None:
    demo = _demo(tmp_path)
    alice_request = _submit(demo, "employee-alice")
    _submit(demo, "employee-bob")
    assert [p.request_id for p in demo.requests_for("employee-alice")] == [alice_request]


def test_manager_list_contains_only_direct_reports(tmp_path) -> None:
    demo = _demo(tmp_path)
    alice_request = _submit(demo, "employee-alice")
    carol_request = _submit(demo, "employee-carol")
    morgan = demo.requests_for("manager-morgan")
    riley = demo.requests_for("manager-riley")
    assert [p.request_id for p in morgan] == [alice_request]
    assert [p.request_id for p in riley] == [carol_request]
    assert all(isinstance(p, ManagerLeaveProjection) for p in (*morgan, *riley))


def test_hr_list_excludes_drafts_and_cancelled(tmp_path) -> None:
    demo = _demo(tmp_path)
    submitted = _submit(demo, "employee-alice")
    demo.create_draft("employee-bob", FORM, "create-bob-draft")
    cancelled = demo.create_draft("employee-carol", FORM, "create-carol-draft")
    demo.cancel_draft("employee-carol", cancelled.request_id, 1, "cancel-carol-01")
    hr_list = demo.requests_for("hr-harper")
    assert [p.request_id for p in hr_list] == [submitted]
    assert isinstance(hr_list[0], HrLeaveProjection)


def test_list_storage_error_becomes_storage_unavailable(tmp_path, monkeypatch) -> None:
    demo = _demo(tmp_path)

    def broken(self):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(SQLiteLeaveRepository, "list_requests", broken)
    with pytest.raises(WorkflowError) as error:
        demo.requests_for("hr-harper")
    assert error.value.code is WorkflowErrorCode.STORAGE_UNAVAILABLE
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --locked pytest tests/unit/app/test_demo_reads.py -q`
Expected: FAIL with `AttributeError: 'DemoApplication' object has no attribute 'ask'`.

- [ ] **Step 3: Implement**

Extend the imports in `app.py`:
- add `visible_requests` to the `access_policy` import;
- add `AssistantOutcome`, `FieldProposalOutcome`, `answer_for_actor`, and `propose_leave_fields` to the `assistant` import;
- add `LeaveStatus` to the `contracts` import.

Add after `RequestView`:

```python
@dataclass(frozen=True, slots=True)
class AskResult:
    outcome: AssistantOutcome
    citations: tuple[CitationInfo, ...]


# Statuses HR never lists: the request has not left the employee's hands (spec, HR page).
_HR_HIDDEN_STATUSES = frozenset({LeaveStatus.DRAFT, LeaveStatus.CANCELLED})
```

Add these methods to `DemoApplication`:

```python
    def ask(self, actor_id: str, question: str) -> AskResult:
        self._actor(actor_id)
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
        self._actor(actor_id)
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --locked pytest tests/unit/app -q && uv run --locked ruff check . && uv run --locked ruff format --check .`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/enterprise_employee_agent/app.py tests/unit/app/test_demo_reads.py
git commit -m "feat: add grounded questions, field proposals, and role lists to the demo app"
```

---

### Task 5: Web foundation — identity, CSRF, errors, and the question page

**Files:**
- Modify: `pyproject.toml`, `uv.lock` (via `uv add`), `Makefile`, `.gitignore`
- Create: `src/enterprise_employee_agent/web/__init__.py`, `session.py`, `errors.py`, `views.py`, `server.py`
- Create: `src/enterprise_employee_agent/web/templates/base.html`, `identity.html`, `ask.html`, `error.html`
- Create: `src/enterprise_employee_agent/web/static/demo.css`
- Test: `tests/unit/web/test_web_foundation.py`

**Interfaces:**
- Consumes: `DemoApplication` (`mode`, `identities`, `identity`, `suggested_questions`, `ask`), `AskResult`, `IdentityOption`, `ERROR_MESSAGES`.
- Produces:
  - `web.session`: `IDENTITY_COOKIE = "demo_identity"`, `ForeignOriginError`, `read_identity(request) -> str`, `set_identity(response, identity_id)`, `clear_identity(response)`, `require_same_origin(request)`
  - `web.errors`: `FORM_CODES`, `CONFLICT_CODES`, `http_status_for(code) -> int`, `error_title(status) -> str`, `GENERIC_ERROR_MESSAGE`, `FOREIGN_ORIGIN_MESSAGE`
  - `web.views`: `HeaderView`, `AnswerView`, `answer_view(result)`
  - `web.server`: `create_app(demo) -> FastAPI` and `create_app_from_env() -> FastAPI`. Inside `create_app`, the helpers `render`, `render_error`, and `new_key()` are available to Task 6.

- [ ] **Step 1: Add dependencies and project plumbing**

```bash
uv add fastapi jinja2 uvicorn python-multipart
```

Expected: `pyproject.toml` `dependencies` gains the four packages and `uv.lock` is updated. Run `uv run --locked python -c "import fastapi, jinja2, uvicorn, multipart"` and expect no output.

Append to `.gitignore`:

```text
var/
```

In `Makefile`, add `demo` to `.PHONY` and append:

```make
demo:
	uv run --locked uvicorn enterprise_employee_agent.web.server:create_app_from_env --factory --host 127.0.0.1 --port 8000
```

- [ ] **Step 2: Write the failing tests**

`tests/unit/web/test_web_foundation.py`:

```python
"""HTTP contracts for identity, CSRF, errors, and the question page (Issue #14)."""

from __future__ import annotations

import itertools
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from enterprise_employee_agent.app import (
    DemoApplication,
    DemoSettings,
    LeaveForm,
    build_demo_application,
)
from enterprise_employee_agent.leave.contracts import WorkflowErrorCode
from enterprise_employee_agent.llm.provider import (
    AnswerProvider,
    AnswerRequest,
    ProviderError,
    ProviderErrorKind,
    ProviderResponse,
)
from enterprise_employee_agent.llm.scripted import ScriptedProvider
from enterprise_employee_agent.web.errors import http_status_for
from enterprise_employee_agent.web.server import create_app

NOW = datetime(2026, 9, 21, 10, 0, tzinfo=UTC)
ORIGIN = {"origin": "http://testserver"}
QUESTION = "How long is parental leave in the US?"
US_DOC = "people-policies/leave-of-absence/us.md"
FORM = LeaveForm(start_date="2026-10-01", end_date="2026-10-05", request_type="continuous")


def _setup(
    tmp_path: Path, *, provider: AnswerProvider | None = None
) -> tuple[TestClient, DemoApplication]:
    counter = itertools.count(1)
    demo = build_demo_application(
        DemoSettings(database_path=tmp_path / "demo.sqlite", openrouter_api_key=None),
        clock=lambda: NOW,
        id_factory=lambda prefix: f"{prefix}-{next(counter):04d}",
        provider=provider,
    )
    return TestClient(create_app(demo)), demo


def _act_as(client: TestClient, identity_id: str) -> None:
    response = client.post(
        "/identity", data={"identity_id": identity_id}, headers=ORIGIN, follow_redirects=False
    )
    assert response.status_code == 303


class _FailingProvider:
    def complete(self, request: AnswerRequest) -> ProviderResponse:
        raise ProviderError(ProviderErrorKind.HTTP_ERROR, "MARKER-7f3a upstream said no")


def test_root_without_identity_redirects_to_chooser(tmp_path) -> None:
    client, _ = _setup(tmp_path)
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/identity"


def test_identity_chooser_lists_all_identities(tmp_path) -> None:
    client, _ = _setup(tmp_path)
    page = client.get("/identity")
    assert page.status_code == 200
    for name in ("Alice Example", "Morgan Manager", "Harper HR"):
        assert name in page.text


def test_choosing_identity_sets_strict_httponly_cookie(tmp_path) -> None:
    client, _ = _setup(tmp_path)
    response = client.post(
        "/identity", data={"identity_id": "hr-harper"}, headers=ORIGIN, follow_redirects=False
    )
    assert response.status_code == 303
    cookie = response.headers["set-cookie"].lower()
    assert cookie.startswith("demo_identity=hr-harper")
    assert "httponly" in cookie
    assert "samesite=strict" in cookie
    assert "path=/" in cookie


def test_header_shows_identity_role_and_offline_mode(tmp_path) -> None:
    client, _ = _setup(tmp_path)
    _act_as(client, "employee-alice")
    page = client.get("/")
    assert page.status_code == 200
    assert "Alice Example" in page.text
    assert "employee-alice" in page.text
    assert "offline · scripted" in page.text
    assert "not a real HR system" in page.text
    assert QUESTION in page.text  # scripted suggestion


def test_unknown_identity_cookie_is_cleared_and_redirected(tmp_path) -> None:
    client, _ = _setup(tmp_path)
    client.cookies.set("demo_identity", "employee-zed")
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/identity"
    assert 'demo_identity=""' in response.headers["set-cookie"] or (
        "max-age=0" in response.headers["set-cookie"].lower()
    )


def test_every_post_route_rejects_missing_and_foreign_origin(tmp_path) -> None:
    client, demo = _setup(tmp_path)
    preview = demo.create_draft("employee-alice", FORM, "create-alice-01")
    client.cookies.set("demo_identity", "employee-alice")
    form = {
        "identity_id": "hr-harper",
        "question": QUESTION,
        "description": "I need leave.",
        "start_date": "2026-11-01",
        "end_date": "2026-11-02",
        "request_type": "intermittent",
        "employee_comment": "",
        "idempotency_key": "key-csrf-00000001",
        "expected_version": "1",
        "payload_digest": preview.confirmation.payload_digest,
    }
    post_paths = [
        route.path.replace("{request_id}", preview.request_id)
        for route in client.app.routes
        if isinstance(route, APIRoute) and "POST" in route.methods
    ]
    assert "/identity" in post_paths and "/ask" in post_paths
    for path in post_paths:
        for headers in ({}, {"origin": "http://evil.example"}, {"origin": "null"}):
            response = client.post(path, data=form, headers=headers, follow_redirects=False)
            assert response.status_code == 403, (path, headers)
            assert "set-cookie" not in response.headers
    view = demo.request_for("employee-alice", preview.request_id)
    assert view.projection.version == 1
    assert len(demo.requests_for("employee-alice")) == 1


def test_referer_is_accepted_when_origin_is_absent(tmp_path) -> None:
    client, _ = _setup(tmp_path)
    response = client.post(
        "/identity",
        data={"identity_id": "hr-harper"},
        headers={"referer": "http://testserver/identity"},
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_ask_renders_answer_with_evidence_link_and_excerpt(tmp_path) -> None:
    client, _ = _setup(tmp_path)
    _act_as(client, "employee-alice")
    page = client.post("/ask", data={"question": QUESTION}, headers=ORIGIN)
    assert page.status_code == 200
    assert "16 weeks" in page.text
    assert "United States Leave of Absence Policies" in page.text
    assert 'href="https://handbook.gitlab.com/handbook/people-policies/leave-of-absence/us/"' in (
        page.text
    )
    assert "<details>" in page.text


def test_escalated_answer_is_labelled_for_hr_review(tmp_path) -> None:
    client, _ = _setup(tmp_path)
    _act_as(client, "employee-alice")
    page = client.post("/ask", data={"question": "Am I eligible for FMLA leave?"}, headers=ORIGIN)
    assert "This needs HR review" in page.text
    assert "Contact HR" in page.text


def test_provider_failure_detail_never_reaches_html(tmp_path) -> None:
    client, _ = _setup(tmp_path, provider=_FailingProvider())
    _act_as(client, "employee-alice")
    page = client.post("/ask", data={"question": QUESTION}, headers=ORIGIN)
    assert page.status_code == 200
    assert "The assistant is unavailable" in page.text
    assert "MARKER-7f3a" not in page.text
    assert "http_error" not in page.text


def test_model_text_markup_is_escaped(tmp_path) -> None:
    content = json.dumps(
        {
            "status": "answered",
            "answer_text": "<script>alert('x')</script> 16 weeks",
            "citations": [US_DOC],
            "clarifying_question": None,
        }
    )
    client, _ = _setup(tmp_path, provider=ScriptedProvider({QUESTION: content}))
    _act_as(client, "employee-alice")
    page = client.post("/ask", data={"question": QUESTION}, headers=ORIGIN)
    assert "<script>alert(" not in page.text
    assert "&lt;script&gt;alert(" in page.text


def test_unknown_route_uses_the_not_found_page(tmp_path) -> None:
    client, _ = _setup(tmp_path)
    response = client.get("/no-such-page")
    assert response.status_code == 404
    assert "The requested leave item was not found." in response.text


def test_unexpected_exception_is_a_generic_500(tmp_path, monkeypatch) -> None:
    client, demo = _setup(tmp_path)
    _act_as(client, "employee-alice")

    def boom(*args, **kwargs):
        raise RuntimeError("SECRET-TRACE-91")

    monkeypatch.setattr(DemoApplication, "ask", boom)
    quiet = TestClient(client.app, raise_server_exceptions=False, cookies=client.cookies)
    response = quiet.post("/ask", data={"question": QUESTION}, headers=ORIGIN)
    assert response.status_code == 500
    assert "SECRET-TRACE-91" not in response.text
    assert "Traceback" not in response.text


@pytest.mark.parametrize(
    ("code", "status"),
    [
        (WorkflowErrorCode.VALIDATION_FAILED, 422),
        (WorkflowErrorCode.SENSITIVE_CONTENT_REJECTED, 422),
        (WorkflowErrorCode.NOT_FOUND, 404),
        (WorkflowErrorCode.FORBIDDEN, 403),
        (WorkflowErrorCode.VERSION_CONFLICT, 409),
        (WorkflowErrorCode.STALE_CONFIRMATION, 409),
        (WorkflowErrorCode.INVALID_TRANSITION, 409),
        (WorkflowErrorCode.IDEMPOTENCY_CONFLICT, 409),
        (WorkflowErrorCode.STORAGE_UNAVAILABLE, 503),
        (WorkflowErrorCode.UNAUTHORIZED, 303),
    ],
)
def test_error_status_table(code, status) -> None:
    assert http_status_for(code) == status


def test_error_status_table_covers_every_code() -> None:
    for code in WorkflowErrorCode:
        http_status_for(code)


def test_pages_have_labels_for_every_text_control(tmp_path) -> None:
    client, _ = _setup(tmp_path)
    _act_as(client, "employee-alice")
    page = client.get("/").text
    for control_id in re.findall(r'<(?:textarea|select|input)[^>]* id="([a-z_]+)"', page):
        assert f'for="{control_id}"' in page, control_id
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run --locked pytest tests/unit/web/test_web_foundation.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'enterprise_employee_agent.web'`.

- [ ] **Step 4: Implement `session.py`, `errors.py`, `views.py`**

`src/enterprise_employee_agent/web/__init__.py`:

```python
"""Server-rendered HTTP boundary for the v0.1 demo (Issue #14)."""
```

`src/enterprise_employee_agent/web/session.py`:

```python
"""Identity cookie and same-origin POST check (decision 0006)."""

# ANCHOR: The identity cookie is a demo switcher, not authentication: unsigned by design and
# re-resolved by DemoApplication on every request. CSRF protection is SameSite=Strict on that
# cookie plus require_same_origin on every POST: Origin (or Referer when Origin is absent) must
# match this app's own scheme and host:port. A missing, "null", or foreign value raises
# ForeignOriginError before any DemoApplication call.

from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import Request, Response

from enterprise_employee_agent.leave.contracts import WorkflowError, WorkflowErrorCode

IDENTITY_COOKIE = "demo_identity"


class ForeignOriginError(Exception):
    """A POST that did not come from this app's own pages."""


def read_identity(request: Request) -> str:
    value = request.cookies.get(IDENTITY_COOKIE)
    if not value:
        raise WorkflowError(WorkflowErrorCode.UNAUTHORIZED)
    return value


def set_identity(response: Response, identity_id: str) -> None:
    response.set_cookie(
        IDENTITY_COOKIE, identity_id, httponly=True, samesite="strict", path="/"
    )


def clear_identity(response: Response) -> None:
    response.delete_cookie(IDENTITY_COOKIE, path="/", httponly=True, samesite="strict")


def require_same_origin(request: Request) -> None:
    claimed = request.headers.get("origin") or request.headers.get("referer")
    if not claimed:
        raise ForeignOriginError
    parsed = urlsplit(claimed)
    own = request.base_url
    if not parsed.scheme or (parsed.scheme, parsed.netloc) != (own.scheme, own.netloc):
        raise ForeignOriginError
```

`src/enterprise_employee_agent/web/errors.py`:

```python
"""WorkflowError code -> HTTP status and page titles for the demo UI (Issue #14)."""

from __future__ import annotations

from enterprise_employee_agent.leave.contracts import WorkflowErrorCode

FORM_CODES = frozenset(
    {WorkflowErrorCode.VALIDATION_FAILED, WorkflowErrorCode.SENSITIVE_CONTENT_REJECTED}
)
CONFLICT_CODES = frozenset(
    {
        WorkflowErrorCode.VERSION_CONFLICT,
        WorkflowErrorCode.STALE_CONFIRMATION,
        WorkflowErrorCode.INVALID_TRANSITION,
        WorkflowErrorCode.IDEMPOTENCY_CONFLICT,
    }
)
_STATUS: dict[WorkflowErrorCode, int] = {
    WorkflowErrorCode.VALIDATION_FAILED: 422,
    WorkflowErrorCode.SENSITIVE_CONTENT_REJECTED: 422,
    WorkflowErrorCode.NOT_FOUND: 404,
    WorkflowErrorCode.FORBIDDEN: 403,
    WorkflowErrorCode.UNAUTHORIZED: 303,
    WorkflowErrorCode.VERSION_CONFLICT: 409,
    WorkflowErrorCode.STALE_CONFIRMATION: 409,
    WorkflowErrorCode.INVALID_TRANSITION: 409,
    WorkflowErrorCode.IDEMPOTENCY_CONFLICT: 409,
    WorkflowErrorCode.STORAGE_UNAVAILABLE: 503,
}
_TITLES = {
    403: "Not available",
    404: "Not found",
    409: "The request changed",
    422: "Check the entered data",
    503: "Storage unavailable",
}
GENERIC_ERROR_MESSAGE = "Something went wrong in the demo. Try again."
FOREIGN_ORIGIN_MESSAGE = "This form did not come from the demo page, so it was rejected."


def http_status_for(code: WorkflowErrorCode) -> int:
    return _STATUS[code]


def error_title(status: int) -> str:
    return _TITLES.get(status, "Something went wrong")
```

`src/enterprise_employee_agent/web/views.py`:

```python
"""Display-only view models for the demo templates (Issue #14)."""

# ANCHOR: Flat display data built from DemoApplication results. This is the filter that keeps
# AssistantFailure (detail, error_kind, violation_kind), provider status codes, and schema names
# out of every template: nothing here reads outcome.failure. Labels are code-owned and never
# imply eligibility or a real GitLab/HRIS integration.

from __future__ import annotations

from dataclasses import dataclass

from enterprise_employee_agent.app import AskResult, CitationInfo, IdentityOption
from enterprise_employee_agent.leave.assistant import AssistantOutcomeKind


@dataclass(frozen=True, slots=True)
class HeaderView:
    identity: IdentityOption | None
    mode_label: str
    identities: tuple[IdentityOption, ...]


@dataclass(frozen=True, slots=True)
class AnswerView:
    status_label: str
    answer_text: str | None
    clarifying_question: str | None
    guidance: str
    citations: tuple[CitationInfo, ...]


_OUTCOME_LABELS = {
    AssistantOutcomeKind.ANSWERED: "Answer from the handbook excerpt",
    AssistantOutcomeKind.ABSTAINED: "The available handbook excerpts do not answer this",
    AssistantOutcomeKind.ESCALATED: "This needs HR review",
    AssistantOutcomeKind.UNAVAILABLE: "The assistant is unavailable",
}


def answer_view(result: AskResult) -> AnswerView:
    outcome = result.outcome
    answer = outcome.answer
    return AnswerView(
        status_label=_OUTCOME_LABELS[outcome.kind],
        answer_text=answer.answer_text if answer is not None else None,
        clarifying_question=answer.clarifying_question if answer is not None else None,
        guidance=outcome.guidance,
        citations=result.citations,
    )
```

- [ ] **Step 5: Implement templates and CSS**

`src/enterprise_employee_agent/web/templates/base.html`:

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}Leave assistant demo{% endblock %}</title>
  <link rel="stylesheet" href="/static/demo.css">
</head>
<body>
  <a class="skip" href="#main">Skip to content</a>
  <p class="banner" role="note">Educational demo — not a real HR system and not connected to GitLab, Tilt, or any HRIS.</p>
  <header>
    {% if header.identity %}
    <p class="who">Acting as <strong>{{ header.identity.display_name }}</strong> (<code>{{ header.identity.identity_id }}</code>) · role: <strong>{{ header.identity.role.value }}</strong></p>
    {% else %}
    <p class="who">No identity selected</p>
    {% endif %}
    <p class="mode">Model mode: <strong>{{ header.mode_label }}</strong></p>
    <form method="post" action="/identity" class="switcher">
      <label for="identity_id">Switch identity</label>
      <select id="identity_id" name="identity_id">
        {% for option in header.identities %}
        <option value="{{ option.identity_id }}"{% if header.identity and option.identity_id == header.identity.identity_id %} selected{% endif %}>{{ option.display_name }} ({{ option.role.value }})</option>
        {% endfor %}
      </select>
      <button type="submit">Switch</button>
    </form>
    <nav aria-label="Main">
      <a href="/">Ask</a>
      <a href="/requests">Requests</a>
      {% if header.identity and header.identity.role.value == "employee" %}<a href="/requests/new">New request</a>{% endif %}
    </nav>
  </header>
  <main id="main">
    {% block content %}{% endblock %}
  </main>
  <script>
    document.addEventListener("submit", function (event) {
      var button = event.target.querySelector("button[type=submit]");
      if (button) { button.disabled = true; button.textContent = "Sending…"; }
    });
  </script>
</body>
</html>
```

`src/enterprise_employee_agent/web/templates/identity.html`:

```html
{% extends "base.html" %}
{% block title %}Choose identity · Leave assistant demo{% endblock %}
{% block content %}
<h1>Choose a demo identity</h1>
<p>All identities are synthetic. Choosing one is not authentication; it shows what each role may see and do.</p>
<ul class="choices">
  {% for option in header.identities %}
  <li>
    <form method="post" action="/identity">
      <input type="hidden" name="identity_id" value="{{ option.identity_id }}">
      <button type="submit">{{ option.display_name }} — {{ option.role.value }}</button>
    </form>
  </li>
  {% endfor %}
</ul>
{% endblock %}
```

`src/enterprise_employee_agent/web/templates/ask.html`:

```html
{% extends "base.html" %}
{% block title %}Ask · Leave assistant demo{% endblock %}
{% block content %}
<h1>Ask about leave policy</h1>
<form method="post" action="/ask">
  <label for="question">Your question</label>
  <textarea id="question" name="question" rows="3" maxlength="1000" required>{{ question }}</textarea>
  <button type="submit">Ask</button>
</form>
{% if suggestions %}
<h2>Scripted questions (offline mode)</h2>
<ul class="choices">
  {% for suggestion in suggestions %}
  <li>
    <form method="post" action="/ask">
      <input type="hidden" name="question" value="{{ suggestion }}">
      <button type="submit">{{ suggestion }}</button>
    </form>
  </li>
  {% endfor %}
</ul>
{% endif %}
{% if answer %}
<section aria-labelledby="answer-heading" class="answer">
  <h2 id="answer-heading">{{ answer.status_label }}</h2>
  {% if answer.answer_text %}<p>{{ answer.answer_text }}</p>{% endif %}
  {% if answer.clarifying_question %}<p><strong>The assistant asks:</strong> {{ answer.clarifying_question }}</p>{% endif %}
  <p class="guidance">{{ answer.guidance }}</p>
  {% if answer.citations %}
  <h3>Evidence</h3>
  <ul class="evidence">
    {% for citation in answer.citations %}
    <li>
      {% if citation.source_url %}<a href="{{ citation.source_url }}">{{ citation.title }}</a>{% else %}<code>{{ citation.document_id }}</code> — internal synthetic document{% endif %}
      <details>
        <summary>Show excerpt</summary>
        <pre>{{ citation.excerpt }}</pre>
      </details>
    </li>
    {% endfor %}
  </ul>
  {% endif %}
</section>
{% endif %}
<p class="fine">Answers use only handbook excerpts your role may read. They are not eligibility decisions.</p>
{% endblock %}
```

`src/enterprise_employee_agent/web/templates/error.html`:

```html
{% extends "base.html" %}
{% block title %}{{ title }} · Leave assistant demo{% endblock %}
{% block content %}
<h1>{{ title }}</h1>
<p role="alert">{{ message }}</p>
<p><a href="/">Back to the assistant</a></p>
{% endblock %}
```

`src/enterprise_employee_agent/web/static/demo.css`:

```css
:root { color-scheme: light; --ink: #1a1a1a; --accent: #0b5cad; --warn: #fff3c4; --err: #8a1c1c; }
* { box-sizing: border-box; }
body { margin: 0 auto; max-width: 48rem; padding: 1rem; font: 1rem/1.5 system-ui, sans-serif; color: var(--ink); background: #fff; }
a { color: var(--accent); }
:focus-visible { outline: 3px solid var(--accent); outline-offset: 2px; }
.skip { position: absolute; left: -999px; }
.skip:focus { left: 1rem; top: 1rem; background: #fff; padding: .25rem .5rem; }
.banner { background: var(--warn); padding: .5rem .75rem; border: 1px solid #b08900; }
header { border-bottom: 1px solid #ccc; margin-bottom: 1rem; padding-bottom: .5rem; }
header p { margin: .25rem 0; }
nav a { margin-right: 1rem; }
label { display: block; font-weight: 600; margin-top: .75rem; }
input, select, textarea, button { font: inherit; }
input, select, textarea { width: 100%; padding: .4rem; border: 1px solid #555; }
button { margin-top: .75rem; padding: .45rem .9rem; border: 1px solid var(--accent); background: var(--accent); color: #fff; cursor: pointer; }
button:disabled { opacity: .6; cursor: wait; }
.switcher { display: flex; flex-wrap: wrap; gap: .5rem; align-items: end; }
.switcher label { margin: 0; width: 100%; }
.switcher select { flex: 1 1 12rem; width: auto; }
.switcher button { margin-top: 0; }
.choices { list-style: none; padding: 0; }
.choices button { width: 100%; text-align: left; background: #fff; color: var(--accent); }
.error { color: var(--err); font-weight: 600; }
.note { background: #eef4fb; padding: .5rem; }
pre { white-space: pre-wrap; word-break: break-word; background: #f5f5f5; padding: .5rem; }
.table-wrap { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; }
th, td { border-bottom: 1px solid #ddd; padding: .35rem; text-align: left; }
dl.fields { display: grid; grid-template-columns: max-content 1fr; gap: .25rem 1rem; }
dl.fields dd { margin: 0; overflow-wrap: anywhere; }
.preview { border: 2px solid var(--accent); padding: .75rem; margin: 1rem 0; }
.fine { font-size: .9rem; color: #444; }
```

- [ ] **Step 6: Implement `server.py`**

`src/enterprise_employee_agent/web/server.py`:

```python
"""FastAPI routes for the v0.1 demo UI (Issue #14)."""

# ANCHOR: Routes, templates, and error mapping only. Every handler reads the actor id from the
# identity cookie and passes it to DemoApplication; no handler resolves identities, checks roles,
# or applies business rules. Every POST first passes require_same_origin (decision 0006). Every
# mutating POST ends in a 303 redirect; /ask and /requests/propose render. Templates receive
# only views.py display data. The app is built by create_app_from_env when uvicorn starts
# (--factory), so importing this module never creates a database.

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, Form, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from enterprise_employee_agent.app import DemoApplication, DemoSettings, build_demo_application
from enterprise_employee_agent.leave.contracts import (
    ERROR_MESSAGES,
    WorkflowError,
    WorkflowErrorCode,
)
from enterprise_employee_agent.web import views
from enterprise_employee_agent.web.errors import (
    FOREIGN_ORIGIN_MESSAGE,
    GENERIC_ERROR_MESSAGE,
    error_title,
    http_status_for,
)
from enterprise_employee_agent.web.session import (
    IDENTITY_COOKIE,
    ForeignOriginError,
    clear_identity,
    read_identity,
    require_same_origin,
    set_identity,
)

_WEB_DIR = Path(__file__).parent
_LOG = logging.getLogger(__name__)
SAME_ORIGIN = [Depends(require_same_origin)]


def new_key() -> str:
    """A fresh idempotency key for one rendered form; not a CSRF token (decision 0006)."""

    return uuid4().hex


def create_app(demo: DemoApplication) -> FastAPI:
    app = FastAPI(
        title="Enterprise Employee Agent demo", docs_url=None, redoc_url=None, openapi_url=None
    )
    templates = Jinja2Templates(directory=_WEB_DIR / "templates")
    app.mount("/static", StaticFiles(directory=_WEB_DIR / "static"), name="static")

    def header(request: Request) -> views.HeaderView:
        identity = None
        actor_id = request.cookies.get(IDENTITY_COOKIE)
        if actor_id:
            try:
                identity = demo.identity(actor_id)
            except WorkflowError:
                identity = None
        return views.HeaderView(
            identity=identity, mode_label=demo.mode().label, identities=demo.identities()
        )

    def render(request: Request, name: str, *, status_code: int = 200, **context) -> Response:
        return templates.TemplateResponse(
            request, name, {"header": header(request), **context}, status_code=status_code
        )

    def render_error(request: Request, status_code: int, message: str) -> Response:
        return render(
            request,
            "error.html",
            status_code=status_code,
            title=error_title(status_code),
            message=message,
        )

    @app.exception_handler(WorkflowError)
    async def handle_workflow_error(request: Request, error: WorkflowError) -> Response:
        if error.code is WorkflowErrorCode.UNAUTHORIZED:
            response = RedirectResponse("/identity", status_code=303)
            clear_identity(response)
            return response
        return render_error(request, http_status_for(error.code), ERROR_MESSAGES[error.code])

    @app.exception_handler(ForeignOriginError)
    async def handle_foreign_origin(request: Request, error: ForeignOriginError) -> Response:
        return render_error(request, 403, FOREIGN_ORIGIN_MESSAGE)

    @app.exception_handler(RequestValidationError)
    async def handle_invalid_form(request: Request, error: RequestValidationError) -> Response:
        return render_error(request, 422, ERROR_MESSAGES[WorkflowErrorCode.VALIDATION_FAILED])

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(request: Request, error: StarletteHTTPException) -> Response:
        if error.status_code == 404:
            return render_error(request, 404, ERROR_MESSAGES[WorkflowErrorCode.NOT_FOUND])
        return render_error(request, error.status_code, GENERIC_ERROR_MESSAGE)

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, error: Exception) -> Response:
        _LOG.exception("unhandled error in demo UI", exc_info=error)
        return render_error(request, 500, GENERIC_ERROR_MESSAGE)

    @app.get("/identity")
    def identity_page(request: Request) -> Response:
        return render(request, "identity.html")

    @app.post("/identity", dependencies=SAME_ORIGIN)
    def choose_identity(identity_id: Annotated[str, Form()] = "") -> Response:
        chosen = demo.identity(identity_id)
        response = RedirectResponse("/", status_code=303)
        set_identity(response, chosen.identity_id)
        return response

    @app.get("/")
    def ask_page(request: Request) -> Response:
        demo.identity(read_identity(request))
        return render(
            request, "ask.html", question="", answer=None, suggestions=demo.suggested_questions()
        )

    @app.post("/ask", dependencies=SAME_ORIGIN)
    def ask(request: Request, question: Annotated[str, Form()] = "") -> Response:
        result = demo.ask(read_identity(request), question)
        return render(
            request,
            "ask.html",
            question=question,
            answer=views.answer_view(result),
            suggestions=demo.suggested_questions(),
        )

    return app


def create_app_from_env() -> FastAPI:
    """uvicorn factory (``--factory``): compose the demo only when the server starts."""

    return create_app(build_demo_application(DemoSettings.from_env()))
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run --locked pytest tests/unit/web -q && uv run --locked pytest -q && uv run --locked ruff check . && uv run --locked ruff format --check .`
Expected: PASS.

If `test_every_post_route_rejects_missing_and_foreign_origin` returns 422 instead of 403, FastAPI validated the form before the dependency ran. Keep the dependency and re-check that every field the route needs is in `form`. Do not move the check into the handler body. If `test_unexpected_exception_is_a_generic_500` fails because the `cookies=` argument is unsupported by the installed `TestClient`, set `quiet.cookies.set("demo_identity", "employee-alice")` instead.

- [ ] **Step 8: Manual smoke**

Run: `make demo` in one terminal, then `curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/identity`.
Expected: `200`. Stop the server, then run `ls var/` and expect `demo.sqlite`. `git status` must not list `var/`.

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml uv.lock Makefile .gitignore src/enterprise_employee_agent/web tests/unit/web/test_web_foundation.py
git commit -m "feat: add server-rendered demo shell with identity switcher and CSRF check"
```

---

### Task 6: Web request pages — draft, preview, confirmation, HR actions, clarification

**Files:**
- Modify: `src/enterprise_employee_agent/web/views.py`, `src/enterprise_employee_agent/web/server.py`
- Create: `src/enterprise_employee_agent/web/templates/requests.html`, `request_new.html`, `request_form.html`, `request.html`, `_leave_fields.html`
- Test: `tests/unit/web/test_web_requests.py`

**Interfaces:**
- Consumes: Task 3/4 `DemoApplication` methods, `LeaveForm`, `RequestView`; Task 5 `render`, `render_error`, `new_key`, `SAME_ORIGIN`, `FORM_CODES`, `CONFLICT_CODES`.
- Produces:
  - Routes: `GET /requests`, `GET /requests/new`, `POST /requests/propose`, `POST /requests`, `GET /requests/{request_id}`, `GET /requests/{request_id}/edit`, and `POST /requests/{request_id}/{edit|cancel|confirm|start-processing|clarification-request|clarification-response}`.
  - Every form writes hidden inputs exactly as `<input type="hidden" name="NAME" value="VALUE">`. The tests' `_form` helper and the Task 7 integration test depend on this exact attribute order.

- [ ] **Step 1: Write the failing tests**

`tests/unit/web/test_web_requests.py`:

```python
"""HTTP contracts for leave request pages (Issue #14)."""

from __future__ import annotations

import itertools
import re
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from enterprise_employee_agent.app import (
    DemoApplication,
    DemoSettings,
    LeaveForm,
    build_demo_application,
)
from enterprise_employee_agent.leave.contracts import LeaveStatus
from enterprise_employee_agent.web.server import create_app

NOW = datetime(2026, 9, 21, 10, 0, tzinfo=UTC)
ORIGIN = {"origin": "http://testserver"}
DESCRIPTION = "I need continuous leave from 2026-10-01 to 2026-10-05 for a family matter."
FIELDS = {
    "start_date": "2026-10-01",
    "end_date": "2026-10-05",
    "request_type": "continuous",
    "employee_comment": "Family matter.",
}
FORM = LeaveForm(**FIELDS)


def _setup(tmp_path: Path) -> tuple[TestClient, DemoApplication]:
    counter = itertools.count(1)
    demo = build_demo_application(
        DemoSettings(database_path=tmp_path / "demo.sqlite", openrouter_api_key=None),
        clock=lambda: NOW,
        id_factory=lambda prefix: f"{prefix}-{next(counter):04d}",
    )
    return TestClient(create_app(demo)), demo


def _act_as(client: TestClient, identity_id: str) -> None:
    response = client.post(
        "/identity", data={"identity_id": identity_id}, headers=ORIGIN, follow_redirects=False
    )
    assert response.status_code == 303


def _form(html: str, action: str) -> dict[str, str]:
    match = re.search(rf'<form method="post" action="{re.escape(action)}">.*?</form>', html, re.S)
    assert match is not None, f"no form posting to {action}"
    return dict(re.findall(r'<input type="hidden" name="([a-z_]+)" value="([^"]*)">', match[0]))


def _post(client: TestClient, path: str, data: dict[str, str]):
    return client.post(path, data=data, headers=ORIGIN, follow_redirects=False)


def _submitted(demo: DemoApplication) -> str:
    preview = demo.create_draft("employee-alice", FORM, "create-alice-01")
    demo.confirm(
        "employee-alice", preview.request_id, 1, preview.confirmation.payload_digest, "confirm-01"
    )
    return preview.request_id


def test_propose_prefills_editable_form_with_fresh_key(tmp_path) -> None:
    client, _ = _setup(tmp_path)
    _act_as(client, "employee-alice")
    assert client.get("/requests/new").status_code == 200
    page = client.post("/requests/propose", data={"description": DESCRIPTION}, headers=ORIGIN)
    assert page.status_code == 200
    assert 'value="2026-10-01"' in page.text
    assert 'value="2026-10-05"' in page.text
    assert re.fullmatch(r"[0-9a-f]{32}", _form(page.text, "/requests")["idempotency_key"])
    assert "actor_id" not in page.text


def test_propose_failure_shows_empty_form_with_manual_note(tmp_path) -> None:
    client, _ = _setup(tmp_path)
    _act_as(client, "employee-alice")
    page = client.post("/requests/propose", data={"description": "Time off pls"}, headers=ORIGIN)
    assert page.status_code == 200
    assert "Fill in the fields manually" in page.text
    assert 'id="start_date" name="start_date" type="date" value=""' in page.text


def test_create_redirects_to_preview_with_version_and_digest(tmp_path) -> None:
    client, demo = _setup(tmp_path)
    _act_as(client, "employee-alice")
    response = _post(client, "/requests", {**FIELDS, "idempotency_key": "key-create-000001"})
    assert response.status_code == 303
    assert response.headers["location"] == "/requests/leave-0001"
    page = client.get("/requests/leave-0001")
    preview = demo.request_for("employee-alice", "leave-0001").preview
    assert "Confirm and submit version 1" in page.text
    confirm = _form(page.text, "/requests/leave-0001/confirm")
    assert confirm["expected_version"] == "1"
    assert confirm["payload_digest"] == preview.confirmation.payload_digest
    assert set(confirm) == {"idempotency_key", "expected_version", "payload_digest"}


def test_actor_id_form_field_is_ignored(tmp_path) -> None:
    client, demo = _setup(tmp_path)
    _act_as(client, "employee-alice")
    data = {**FIELDS, "idempotency_key": "key-create-000001", "actor_id": "employee-bob"}
    assert _post(client, "/requests", data).status_code == 303
    assert demo.requests_for("employee-bob") == ()
    assert len(demo.requests_for("employee-alice")) == 1


def test_invalid_fields_rerender_form_with_values_and_422(tmp_path) -> None:
    client, _ = _setup(tmp_path)
    _act_as(client, "employee-alice")
    data = {**FIELDS, "end_date": "2026-09-01", "idempotency_key": "key-create-000001"}
    page = _post(client, "/requests", data)
    assert page.status_code == 422
    assert "The request data is invalid." in page.text
    assert 'value="2026-09-01"' in page.text
    assert 'aria-describedby="form-error"' in page.text


def test_same_key_replays_and_different_data_conflicts(tmp_path) -> None:
    client, _ = _setup(tmp_path)
    _act_as(client, "employee-alice")
    data = {**FIELDS, "idempotency_key": "key-create-000001"}
    first = _post(client, "/requests", data)
    second = _post(client, "/requests", data)
    assert first.headers["location"] == second.headers["location"]
    conflict = _post(client, "/requests", {**data, "end_date": "2026-10-09"})
    assert conflict.status_code == 409
    assert "This operation key was used for different data." in conflict.text


def test_foreign_and_missing_requests_render_the_same_404(tmp_path) -> None:
    client, demo = _setup(tmp_path)
    request_id = _submitted(demo)
    _act_as(client, "employee-bob")
    foreign = client.get(f"/requests/{request_id}")
    missing = client.get("/requests/leave-9999")
    assert foreign.status_code == missing.status_code == 404
    assert foreign.text == missing.text


def test_manager_cannot_create_requests(tmp_path) -> None:
    client, _ = _setup(tmp_path)
    _act_as(client, "manager-morgan")
    response = _post(client, "/requests", {**FIELDS, "idempotency_key": "key-create-000001"})
    assert response.status_code == 403
    assert "This action is not available to the selected identity." in response.text


def test_stale_confirmation_is_409_with_fresh_preview(tmp_path) -> None:
    client, _ = _setup(tmp_path)
    _act_as(client, "employee-alice")
    _post(client, "/requests", {**FIELDS, "idempotency_key": "key-create-000001"})
    old_confirm = _form(client.get("/requests/leave-0001").text, "/requests/leave-0001/confirm")
    edit = _form(client.get("/requests/leave-0001/edit").text, "/requests/leave-0001/edit")
    changed = _post(client, "/requests/leave-0001/edit", {**edit, **FIELDS, "end_date": "2026-10-06"})
    assert changed.status_code == 303
    stale = _post(client, "/requests/leave-0001/confirm", old_confirm)
    assert stale.status_code == 409
    assert "The preview changed; review and confirm it again." in stale.text
    assert "Confirm and submit version 2" in stale.text


def test_cancel_draft(tmp_path) -> None:
    client, demo = _setup(tmp_path)
    _act_as(client, "employee-alice")
    _post(client, "/requests", {**FIELDS, "idempotency_key": "key-create-000001"})
    cancel = _form(client.get("/requests/leave-0001").text, "/requests/leave-0001/cancel")
    assert _post(client, "/requests/leave-0001/cancel", cancel).status_code == 303
    assert demo.request_for("employee-alice", "leave-0001").projection.status is (
        LeaveStatus.CANCELLED
    )


def test_hr_sees_audit_history_and_can_start_processing(tmp_path) -> None:
    client, demo = _setup(tmp_path)
    request_id = _submitted(demo)
    _act_as(client, "hr-harper")
    listing = client.get("/requests")
    assert request_id in listing.text
    page = client.get(f"/requests/{request_id}")
    assert "Audit history" in page.text
    assert "Family matter." in page.text
    start = _form(page.text, f"/requests/{request_id}/start-processing")
    assert _post(client, f"/requests/{request_id}/start-processing", start).status_code == 303
    assert demo.request_for("hr-harper", request_id).projection.status is LeaveStatus.PROCESSING


def test_hr_list_hides_drafts(tmp_path) -> None:
    client, demo = _setup(tmp_path)
    demo.create_draft("employee-alice", FORM, "create-alice-01")
    _act_as(client, "hr-harper")
    page = client.get("/requests")
    assert "leave-0001" not in page.text
    assert "No requests to show." in page.text


def test_manager_page_renders_only_the_manager_projection(tmp_path) -> None:
    client, demo = _setup(tmp_path)
    request_id = _submitted(demo)
    _act_as(client, "manager-morgan")
    page = client.get(f"/requests/{request_id}")
    assert page.status_code == 200
    assert "submitted" in page.text
    assert "Family matter." not in page.text
    assert "Audit history" not in page.text
    assert f'action="/requests/{request_id}/' not in page.text
    _act_as(client, "manager-riley")
    assert client.get(f"/requests/{request_id}").status_code == 404


def test_hr_blank_clarification_question_is_422_on_the_request_page(tmp_path) -> None:
    client, demo = _setup(tmp_path)
    request_id = _submitted(demo)
    _act_as(client, "hr-harper")
    form = _form(client.get(f"/requests/{request_id}").text, f"/requests/{request_id}/clarification-request")
    page = _post(client, f"/requests/{request_id}/clarification-request", {**form, "question": " "})
    assert page.status_code == 422
    assert "The request data is invalid." in page.text


def test_clarification_round_trip_through_forms(tmp_path) -> None:
    client, demo = _setup(tmp_path)
    request_id = _submitted(demo)
    _act_as(client, "hr-harper")
    ask = _form(client.get(f"/requests/{request_id}").text, f"/requests/{request_id}/clarification-request")
    response = _post(
        client,
        f"/requests/{request_id}/clarification-request",
        {**ask, "question": "Please confirm the end date."},
    )
    assert response.status_code == 303

    _act_as(client, "employee-alice")
    page = client.get(f"/requests/{request_id}")
    assert "Please confirm the end date." in page.text
    answer = _form(page.text, f"/requests/{request_id}/clarification-response")
    response = _post(
        client,
        f"/requests/{request_id}/clarification-response",
        {**answer, **FIELDS, "end_date": "2026-10-06"},
    )
    assert response.status_code == 303
    page = client.get(f"/requests/{request_id}")
    confirm = _form(page.text, f"/requests/{request_id}/confirm")
    assert _post(client, f"/requests/{request_id}/confirm", confirm).status_code == 303
    assert demo.request_for("employee-alice", request_id).projection.status is (
        LeaveStatus.SUBMITTED
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --locked pytest tests/unit/web/test_web_requests.py -q`
Expected: FAIL, mostly with `404` responses for `/requests/...` routes.

- [ ] **Step 3: Extend `views.py`**

Add imports: `LeaveForm`, `RequestView` from `app`; `LeaveProjection` from `leave.access_policy`; `FieldProposalOutcome`, `FieldProposalOutcomeKind` from `leave.assistant`; `ActorRole`, `CommandName`, `EmployeeLeaveProjection` from `leave.contracts`. Append:

```python
_PROPOSAL_FAILED_NOTE = "The assistant could not read your description. Fill in the fields manually."
_PROPOSAL_INCOMPLETE_NOTE = "Some fields were not in your description. Fill in the empty fields."


def form_from_proposal(outcome: FieldProposalOutcome) -> tuple[LeaveForm, str | None]:
    proposal = outcome.proposal
    if outcome.kind is not FieldProposalOutcomeKind.PROPOSED or proposal is None:
        return LeaveForm(start_date="", end_date="", request_type=""), _PROPOSAL_FAILED_NOTE
    form = LeaveForm(
        start_date=proposal.start_date.isoformat() if proposal.start_date else "",
        end_date=proposal.end_date.isoformat() if proposal.end_date else "",
        request_type=proposal.request_type.value if proposal.request_type else "",
        employee_comment=proposal.employee_comment or "",
    )
    return form, _PROPOSAL_INCOMPLETE_NOTE if proposal.missing_fields() else None


def form_from_projection(projection: EmployeeLeaveProjection) -> LeaveForm:
    return LeaveForm(
        start_date=projection.start_date.isoformat(),
        end_date=projection.end_date.isoformat(),
        request_type=projection.request_type.value,
        employee_comment=projection.employee_comment or "",
    )


@dataclass(frozen=True, slots=True)
class RequestRow:
    request_id: str
    employee_id: str
    status: str
    start_date: str
    end_date: str
    request_type: str


def row_view(projection: LeaveProjection) -> RequestRow:
    return RequestRow(
        request_id=projection.request_id,
        employee_id=projection.employee_id,
        status=projection.status.value,
        start_date=projection.start_date.isoformat(),
        end_date=projection.end_date.isoformat(),
        request_type=projection.request_type.value,
    )


_LIST_HEADINGS = {
    ActorRole.EMPLOYEE: "Your leave requests",
    ActorRole.MANAGER: "Leave requests of your direct reports",
    ActorRole.HR: "Submitted leave requests",
}


def list_heading(role: ActorRole) -> str:
    return _LIST_HEADINGS[role]


# Every field any role projection declares; a new projection field without a label fails loudly.
_FIELD_LABELS = {
    "request_id": "Request",
    "employee_id": "Employee",
    "status": "Status",
    "version": "Version",
    "start_date": "Start date",
    "end_date": "End date",
    "request_type": "Leave type",
    "employee_comment": "Comment",
    "clarification_question": "HR question",
    "updated_at": "Last updated",
}
_HISTORY_FIELDS = {
    "action_history": "Your actions on this request",
    "audit_history": "Audit history",
}


@dataclass(frozen=True, slots=True)
class HistoryRow:
    occurred_at: str
    actor_id: str
    command: str
    new_status: str
    request_version: int


@dataclass(frozen=True, slots=True)
class RequestDetailView:
    request_id: str
    version: int | None
    fields: tuple[tuple[str, str], ...]
    history_label: str | None
    history: tuple[HistoryRow, ...]
    actions: frozenset[str]
    preview_version: int | None
    preview_digest: str | None
    form: LeaveForm | None


def detail_view(view: RequestView) -> RequestDetailView:
    """Render exactly the fields of the role projection ``project_for`` returned."""

    projection = view.projection
    data = projection.model_dump(mode="json")
    fields = tuple(
        (_FIELD_LABELS[name], "" if value is None else str(value))
        for name, value in data.items()
        if name not in _HISTORY_FIELDS
    )
    history_name = next((name for name in _HISTORY_FIELDS if name in data), None)
    events = getattr(projection, history_name) if history_name is not None else ()
    preview = view.preview
    form = None
    if CommandName.PROVIDE_CLARIFICATION in view.actions and isinstance(
        projection, EmployeeLeaveProjection
    ):
        form = form_from_projection(projection)
    return RequestDetailView(
        request_id=projection.request_id,
        version=getattr(projection, "version", None),
        fields=fields,
        history_label=_HISTORY_FIELDS[history_name] if history_name is not None else None,
        history=tuple(
            HistoryRow(
                occurred_at=event.occurred_at.isoformat(),
                actor_id=event.actor_id,
                command=event.command.value,
                new_status=event.new_status.value,
                request_version=event.request_version,
            )
            for event in events
        ),
        actions=frozenset(action.value for action in view.actions),
        preview_version=preview.request_version if preview is not None else None,
        preview_digest=preview.confirmation.payload_digest if preview is not None else None,
        form=form,
    )
```

- [ ] **Step 4: Add templates**

`src/enterprise_employee_agent/web/templates/_leave_fields.html`:

```html
<label for="start_date">Start date</label>
<input id="start_date" name="start_date" type="date" value="{{ form.start_date }}" required{% if error %} aria-describedby="form-error"{% endif %}>
<label for="end_date">End date</label>
<input id="end_date" name="end_date" type="date" value="{{ form.end_date }}" required{% if error %} aria-describedby="form-error"{% endif %}>
<label for="request_type">Leave type</label>
<select id="request_type" name="request_type" required{% if error %} aria-describedby="form-error"{% endif %}>
  <option value="">Choose…</option>
  <option value="continuous"{% if form.request_type == "continuous" %} selected{% endif %}>Continuous</option>
  <option value="intermittent"{% if form.request_type == "intermittent" %} selected{% endif %}>Intermittent</option>
</select>
<label for="employee_comment">Comment (operational details only — no medical information)</label>
<textarea id="employee_comment" name="employee_comment" rows="3" maxlength="500">{{ form.employee_comment }}</textarea>
```

`src/enterprise_employee_agent/web/templates/request_new.html`:

```html
{% extends "base.html" %}
{% block title %}New request · Leave assistant demo{% endblock %}
{% block content %}
<h1>New leave request</h1>
<p>Describe the leave in your own words: the dates and whether it is continuous or intermittent. Do not include medical details. The assistant pre-fills a form for you to check. Nothing is saved until you save the draft.</p>
<form method="post" action="/requests/propose">
  <label for="description">Description</label>
  <textarea id="description" name="description" rows="4" maxlength="1000" required></textarea>
  <button type="submit">Pre-fill the form</button>
</form>
{% if suggestions %}
<h2>Scripted descriptions (offline mode)</h2>
<ul class="choices">
  {% for suggestion in suggestions %}
  <li>
    <form method="post" action="/requests/propose">
      <input type="hidden" name="description" value="{{ suggestion }}">
      <button type="submit">{{ suggestion }}</button>
    </form>
  </li>
  {% endfor %}
</ul>
{% endif %}
{% endblock %}
```

`src/enterprise_employee_agent/web/templates/request_form.html`:

```html
{% extends "base.html" %}
{% block title %}{{ heading }} · Leave assistant demo{% endblock %}
{% block content %}
<h1>{{ heading }}</h1>
{% if note %}<p class="note" role="status">{{ note }}</p>{% endif %}
{% if error %}<p id="form-error" class="error" role="alert">{{ error }}</p>{% endif %}
<form method="post" action="{{ action_url }}">
  <input type="hidden" name="idempotency_key" value="{{ idempotency_key }}">
  {% if expected_version %}<input type="hidden" name="expected_version" value="{{ expected_version }}">{% endif %}
  {% include "_leave_fields.html" %}
  <button type="submit">{{ submit_label }}</button>
</form>
<p class="fine">Saving creates or updates a draft only. Nothing is submitted until you confirm the preview.</p>
{% endblock %}
```

`src/enterprise_employee_agent/web/templates/requests.html`:

```html
{% extends "base.html" %}
{% block title %}Requests · Leave assistant demo{% endblock %}
{% block content %}
<h1>{{ heading }}</h1>
{% if rows %}
<div class="table-wrap">
<table>
  <thead><tr><th scope="col">Request</th><th scope="col">Employee</th><th scope="col">Status</th><th scope="col">Start</th><th scope="col">End</th><th scope="col">Type</th></tr></thead>
  <tbody>
    {% for row in rows %}
    <tr><td><a href="/requests/{{ row.request_id }}">{{ row.request_id }}</a></td><td>{{ row.employee_id }}</td><td>{{ row.status }}</td><td>{{ row.start_date }}</td><td>{{ row.end_date }}</td><td>{{ row.request_type }}</td></tr>
    {% endfor %}
  </tbody>
</table>
</div>
{% else %}
<p>No requests to show.</p>
{% endif %}
{% endblock %}
```

`src/enterprise_employee_agent/web/templates/request.html`:

```html
{% extends "base.html" %}
{% block title %}Request {{ detail.request_id }} · Leave assistant demo{% endblock %}
{% block content %}
<h1>Leave request <code>{{ detail.request_id }}</code></h1>
{% if notice %}<p class="error" role="alert">{{ notice }}</p>{% endif %}
{% if error %}<p id="form-error" class="error" role="alert">{{ error }}</p>{% endif %}
<dl class="fields">
  {% for label, value in detail.fields %}<dt>{{ label }}</dt><dd>{{ value or "—" }}</dd>{% endfor %}
</dl>

{% if "confirm_submit" in detail.actions %}
<section aria-labelledby="preview-heading" class="preview">
  <h2 id="preview-heading">Review and confirm version {{ detail.preview_version }}</h2>
  <p>You are confirming exactly the data above: version {{ detail.preview_version }}, fingerprint <code>{{ detail.preview_digest }}</code>. If the request changes before you confirm, the confirmation is rejected and you review it again.</p>
  <form method="post" action="/requests/{{ detail.request_id }}/confirm">
    <input type="hidden" name="idempotency_key" value="{{ keys.confirm_submit }}">
    <input type="hidden" name="expected_version" value="{{ detail.preview_version }}">
    <input type="hidden" name="payload_digest" value="{{ detail.preview_digest }}">
    <button type="submit">Confirm and submit version {{ detail.preview_version }}</button>
  </form>
</section>
{% endif %}

{% if "update_draft" in detail.actions %}
<p><a href="/requests/{{ detail.request_id }}/edit">Edit draft</a></p>
{% endif %}

{% if "cancel_draft" in detail.actions %}
<form method="post" action="/requests/{{ detail.request_id }}/cancel">
  <input type="hidden" name="idempotency_key" value="{{ keys.cancel_draft }}">
  <input type="hidden" name="expected_version" value="{{ detail.version }}">
  <button type="submit">Cancel draft</button>
</form>
{% endif %}

{% if "provide_clarification" in detail.actions %}
<section aria-labelledby="answer-heading">
  <h2 id="answer-heading">Answer HR's question</h2>
  <p>Correct the fields if needed and save. Then confirm the new version above it again.</p>
  <form method="post" action="/requests/{{ detail.request_id }}/clarification-response">
    <input type="hidden" name="idempotency_key" value="{{ keys.provide_clarification }}">
    <input type="hidden" name="expected_version" value="{{ detail.version }}">
    {% include "_leave_fields.html" %}
    <button type="submit">Save answer</button>
  </form>
</section>
{% endif %}

{% if "start_processing" in detail.actions %}
<form method="post" action="/requests/{{ detail.request_id }}/start-processing">
  <input type="hidden" name="idempotency_key" value="{{ keys.start_processing }}">
  <input type="hidden" name="expected_version" value="{{ detail.version }}">
  <button type="submit">Start processing</button>
</form>
{% endif %}

{% if "request_clarification" in detail.actions %}
<form method="post" action="/requests/{{ detail.request_id }}/clarification-request">
  <input type="hidden" name="idempotency_key" value="{{ keys.request_clarification }}">
  <input type="hidden" name="expected_version" value="{{ detail.version }}">
  <label for="question">Question for the employee (operational only)</label>
  <textarea id="question" name="question" rows="3" maxlength="500" required{% if error %} aria-describedby="form-error"{% endif %}></textarea>
  <button type="submit">Request clarification</button>
</form>
{% endif %}

{% if not detail.actions %}
<p class="fine">No actions are available to this identity for the request in its current status.</p>
{% endif %}

{% if detail.history %}
<h2>{{ detail.history_label }}</h2>
<div class="table-wrap">
<table>
  <thead><tr><th scope="col">When</th><th scope="col">Actor</th><th scope="col">Action</th><th scope="col">New status</th><th scope="col">Version</th></tr></thead>
  <tbody>
    {% for row in detail.history %}
    <tr><td>{{ row.occurred_at }}</td><td>{{ row.actor_id }}</td><td>{{ row.command }}</td><td>{{ row.new_status }}</td><td>{{ row.request_version }}</td></tr>
    {% endfor %}
  </tbody>
</table>
</div>
{% endif %}
<p><a href="/requests">Back to requests</a></p>
{% endblock %}
```

- [ ] **Step 5: Add routes to `server.py`**

Add imports: `from collections.abc import Callable`; `LeaveForm` from `app`; `CommandName` from `leave.contracts`; `CONFLICT_CODES`, `FORM_CODES` from `web.errors`. Insert the following inside `create_app`, before `return app`:

```python
    def leave_form(
        start_date: str, end_date: str, request_type: str, employee_comment: str
    ) -> LeaveForm:
        return LeaveForm(
            start_date=start_date,
            end_date=end_date,
            request_type=request_type,
            employee_comment=employee_comment,
        )

    def render_form(
        request: Request,
        *,
        heading: str,
        action_url: str,
        form: LeaveForm,
        submit_label: str,
        expected_version: int | None = None,
        note: str | None = None,
        error: str | None = None,
        status_code: int = 200,
    ) -> Response:
        return render(
            request,
            "request_form.html",
            status_code=status_code,
            heading=heading,
            action_url=action_url,
            form=form,
            idempotency_key=new_key(),
            expected_version=expected_version,
            note=note,
            error=error,
            submit_label=submit_label,
        )

    def render_detail(
        request: Request,
        actor_id: str,
        request_id: str,
        *,
        status_code: int = 200,
        notice: str | None = None,
        error: str | None = None,
        form: LeaveForm | None = None,
    ) -> Response:
        detail = views.detail_view(demo.request_for(actor_id, request_id))
        return render(
            request,
            "request.html",
            status_code=status_code,
            detail=detail,
            keys={action: new_key() for action in detail.actions},
            notice=notice,
            error=error,
            form=form or detail.form,
        )

    def mutate(
        request: Request,
        actor_id: str,
        request_id: str,
        action: Callable[[], object],
        *,
        on_form_error: Callable[[str], Response] | None = None,
    ) -> Response:
        try:
            action()
        except WorkflowError as error:
            if error.code in CONFLICT_CODES:
                return render_detail(
                    request,
                    actor_id,
                    request_id,
                    status_code=409,
                    notice=ERROR_MESSAGES[error.code],
                )
            if error.code in FORM_CODES and on_form_error is not None:
                return on_form_error(ERROR_MESSAGES[error.code])
            raise
        return RedirectResponse(f"/requests/{request_id}", status_code=303)

    @app.get("/requests")
    def request_list(request: Request) -> Response:
        actor_id = read_identity(request)
        role = demo.identity(actor_id).role
        rows = tuple(views.row_view(p) for p in demo.requests_for(actor_id))
        return render(request, "requests.html", heading=views.list_heading(role), rows=rows)

    @app.get("/requests/new")
    def new_request(request: Request) -> Response:
        demo.identity(read_identity(request))
        return render(
            request, "request_new.html", suggestions=demo.suggested_leave_descriptions()
        )

    @app.post("/requests/propose", dependencies=SAME_ORIGIN)
    def propose(request: Request, description: Annotated[str, Form()] = "") -> Response:
        outcome = demo.propose_fields(read_identity(request), description)
        form, note = views.form_from_proposal(outcome)
        return render_form(
            request,
            heading="Check the pre-filled request",
            action_url="/requests",
            form=form,
            note=note,
            submit_label="Save draft",
        )

    @app.post("/requests", dependencies=SAME_ORIGIN)
    def create(
        request: Request,
        start_date: Annotated[str, Form()] = "",
        end_date: Annotated[str, Form()] = "",
        request_type: Annotated[str, Form()] = "",
        employee_comment: Annotated[str, Form()] = "",
        idempotency_key: Annotated[str, Form()] = "",
    ) -> Response:
        actor_id = read_identity(request)
        form = leave_form(start_date, end_date, request_type, employee_comment)
        try:
            preview = demo.create_draft(actor_id, form, idempotency_key)
        except WorkflowError as error:
            if error.code not in FORM_CODES:
                raise
            return render_form(
                request,
                heading="Check the pre-filled request",
                action_url="/requests",
                form=form,
                error=ERROR_MESSAGES[error.code],
                submit_label="Save draft",
                status_code=422,
            )
        return RedirectResponse(f"/requests/{preview.request_id}", status_code=303)

    @app.get("/requests/{request_id}")
    def request_detail(request: Request, request_id: str) -> Response:
        return render_detail(request, read_identity(request), request_id)

    @app.get("/requests/{request_id}/edit")
    def edit_page(request: Request, request_id: str) -> Response:
        view = demo.request_for(read_identity(request), request_id)
        if CommandName.UPDATE_DRAFT not in view.actions:
            raise WorkflowError(WorkflowErrorCode.INVALID_TRANSITION)
        return render_form(
            request,
            heading="Edit draft",
            action_url=f"/requests/{request_id}/edit",
            form=views.form_from_projection(view.projection),
            expected_version=view.projection.version,
            submit_label="Save changes",
        )

    @app.post("/requests/{request_id}/edit", dependencies=SAME_ORIGIN)
    def edit(
        request: Request,
        request_id: str,
        expected_version: Annotated[int, Form()],
        start_date: Annotated[str, Form()] = "",
        end_date: Annotated[str, Form()] = "",
        request_type: Annotated[str, Form()] = "",
        employee_comment: Annotated[str, Form()] = "",
        idempotency_key: Annotated[str, Form()] = "",
    ) -> Response:
        actor_id = read_identity(request)
        form = leave_form(start_date, end_date, request_type, employee_comment)
        return mutate(
            request,
            actor_id,
            request_id,
            lambda: demo.update_draft(actor_id, request_id, expected_version, form, idempotency_key),
            on_form_error=lambda message: render_form(
                request,
                heading="Edit draft",
                action_url=f"/requests/{request_id}/edit",
                form=form,
                expected_version=expected_version,
                error=message,
                submit_label="Save changes",
                status_code=422,
            ),
        )

    @app.post("/requests/{request_id}/cancel", dependencies=SAME_ORIGIN)
    def cancel(
        request: Request,
        request_id: str,
        expected_version: Annotated[int, Form()],
        idempotency_key: Annotated[str, Form()] = "",
    ) -> Response:
        actor_id = read_identity(request)
        return mutate(
            request,
            actor_id,
            request_id,
            lambda: demo.cancel_draft(actor_id, request_id, expected_version, idempotency_key),
        )

    @app.post("/requests/{request_id}/confirm", dependencies=SAME_ORIGIN)
    def confirm(
        request: Request,
        request_id: str,
        expected_version: Annotated[int, Form()],
        payload_digest: Annotated[str, Form()] = "",
        idempotency_key: Annotated[str, Form()] = "",
    ) -> Response:
        actor_id = read_identity(request)
        return mutate(
            request,
            actor_id,
            request_id,
            lambda: demo.confirm(
                actor_id, request_id, expected_version, payload_digest, idempotency_key
            ),
        )

    @app.post("/requests/{request_id}/start-processing", dependencies=SAME_ORIGIN)
    def start_processing(
        request: Request,
        request_id: str,
        expected_version: Annotated[int, Form()],
        idempotency_key: Annotated[str, Form()] = "",
    ) -> Response:
        actor_id = read_identity(request)
        return mutate(
            request,
            actor_id,
            request_id,
            lambda: demo.hr_start(actor_id, request_id, expected_version, idempotency_key),
        )

    @app.post("/requests/{request_id}/clarification-request", dependencies=SAME_ORIGIN)
    def request_clarification(
        request: Request,
        request_id: str,
        expected_version: Annotated[int, Form()],
        question: Annotated[str, Form()] = "",
        idempotency_key: Annotated[str, Form()] = "",
    ) -> Response:
        actor_id = read_identity(request)
        return mutate(
            request,
            actor_id,
            request_id,
            lambda: demo.hr_clarify(
                actor_id, request_id, expected_version, question, idempotency_key
            ),
            on_form_error=lambda message: render_detail(
                request, actor_id, request_id, status_code=422, error=message
            ),
        )

    @app.post("/requests/{request_id}/clarification-response", dependencies=SAME_ORIGIN)
    def provide_clarification(
        request: Request,
        request_id: str,
        expected_version: Annotated[int, Form()],
        start_date: Annotated[str, Form()] = "",
        end_date: Annotated[str, Form()] = "",
        request_type: Annotated[str, Form()] = "",
        employee_comment: Annotated[str, Form()] = "",
        idempotency_key: Annotated[str, Form()] = "",
    ) -> Response:
        actor_id = read_identity(request)
        form = leave_form(start_date, end_date, request_type, employee_comment)
        return mutate(
            request,
            actor_id,
            request_id,
            lambda: demo.employee_clarify(
                actor_id, request_id, expected_version, form, idempotency_key
            ),
            on_form_error=lambda message: render_detail(
                request, actor_id, request_id, status_code=422, error=message, form=form
            ),
        )
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run --locked pytest tests/unit/web -q && uv run --locked pytest -q && uv run --locked ruff check . && uv run --locked ruff format --check .`
Expected: PASS. The CSRF test from Task 5 now iterates the new POST routes as well and must stay green.

- [ ] **Step 7: Commit**

```bash
git add src/enterprise_employee_agent/web tests/unit/web/test_web_requests.py
git commit -m "feat: add leave request pages with preview, confirmation, and HR actions"
```

---

### Task 7: End-to-end journey, smoke check, and PR

**Files:**
- Create: `tests/integration/test_demo_ui_journey.py`, `tests/smoke/test_demo_ui_smoke.py`

**Interfaces:**
- Consumes: everything above; `create_app_from_env`.

- [ ] **Step 1: Write the tests**

`tests/integration/test_demo_ui_journey.py`:

```python
"""Full v0.1 scenario through the demo UI with the real application (Issue #14)."""

from __future__ import annotations

import itertools
import re
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from enterprise_employee_agent.app import DemoSettings, build_demo_application
from enterprise_employee_agent.web.server import create_app

NOW = datetime(2026, 9, 21, 10, 0, tzinfo=UTC)
ORIGIN = {"origin": "http://testserver"}
QUESTION = "How long is parental leave in the US?"
DESCRIPTION = "I need continuous leave from 2026-10-01 to 2026-10-05 for a family matter."


def _client(tmp_path) -> TestClient:
    counter = itertools.count(1)
    demo = build_demo_application(
        DemoSettings(database_path=tmp_path / "demo.sqlite", openrouter_api_key=None),
        clock=lambda: NOW,
        id_factory=lambda prefix: f"{prefix}-{next(counter):04d}",
    )
    return TestClient(create_app(demo))


def _act_as(client: TestClient, identity_id: str) -> None:
    assert client.post(
        "/identity", data={"identity_id": identity_id}, headers=ORIGIN, follow_redirects=False
    ).status_code == 303


def _form(html: str, action: str) -> dict[str, str]:
    match = re.search(rf'<form method="post" action="{re.escape(action)}">.*?</form>', html, re.S)
    assert match is not None, f"no form posting to {action}"
    return dict(re.findall(r'<input type="hidden" name="([a-z_]+)" value="([^"]*)">', match[0]))


def _post(client: TestClient, path: str, data: dict[str, str]) -> int:
    return client.post(path, data=data, headers=ORIGIN, follow_redirects=False).status_code


def _fields_from(html: str) -> dict[str, str]:
    values = dict(re.findall(r'name="(start_date|end_date)" type="date" value="([^"]*)"', html))
    values["request_type"] = re.search(r'<option value="(\w+)" selected>', html)[1]
    values["employee_comment"] = re.search(r'name="employee_comment"[^>]*>([^<]*)<', html)[1]
    return values


def test_full_demo_journey_through_the_ui(tmp_path) -> None:
    client = _client(tmp_path)

    _act_as(client, "employee-alice")
    answer = client.post("/ask", data={"question": QUESTION}, headers=ORIGIN)
    assert "16 weeks" in answer.text
    assert "United States Leave of Absence Policies" in answer.text

    proposed = client.post("/requests/propose", data={"description": DESCRIPTION}, headers=ORIGIN)
    fields = _fields_from(proposed.text)
    assert fields == {
        "start_date": "2026-10-01",
        "end_date": "2026-10-05",
        "request_type": "continuous",
        "employee_comment": "Family matter.",
    }
    created = client.post(
        "/requests",
        data={**_form(proposed.text, "/requests"), **fields},
        headers=ORIGIN,
        follow_redirects=False,
    )
    assert created.status_code == 303
    url = created.headers["location"]
    request_id = url.rsplit("/", 1)[-1]

    preview = client.get(url)
    assert "Confirm and submit version 1" in preview.text
    assert _post(client, f"{url}/confirm", _form(preview.text, f"{url}/confirm")) == 303

    _act_as(client, "hr-harper")
    assert request_id in client.get("/requests").text
    hr_page = client.get(url)
    assert "Audit history" in hr_page.text
    ask = _form(hr_page.text, f"{url}/clarification-request")
    assert _post(client, f"{url}/clarification-request", {**ask, "question": "Confirm the end date."}) == 303

    _act_as(client, "employee-alice")
    page = client.get(url)
    assert "Confirm the end date." in page.text
    reply = _form(page.text, f"{url}/clarification-response")
    assert _post(client, f"{url}/clarification-response", {**reply, **fields, "end_date": "2026-10-06"}) == 303
    page = client.get(url)
    assert "2026-10-06" in page.text
    assert _post(client, f"{url}/confirm", _form(page.text, f"{url}/confirm")) == 303

    _act_as(client, "hr-harper")
    page = client.get(url)
    assert _post(client, f"{url}/start-processing", _form(page.text, f"{url}/start-processing")) == 303

    _act_as(client, "manager-morgan")
    manager_page = client.get(url)
    assert manager_page.status_code == 200
    assert "processing" in manager_page.text
    assert "Family matter." not in manager_page.text

    _act_as(client, "manager-riley")
    assert client.get(url).status_code == 404


def test_stale_confirmation_is_visibly_rejected(tmp_path) -> None:
    client = _client(tmp_path)
    _act_as(client, "employee-alice")
    proposed = client.post("/requests/propose", data={"description": DESCRIPTION}, headers=ORIGIN)
    created = client.post(
        "/requests",
        data={**_form(proposed.text, "/requests"), **_fields_from(proposed.text)},
        headers=ORIGIN,
        follow_redirects=False,
    )
    url = created.headers["location"]
    stale = _form(client.get(url).text, f"{url}/confirm")
    edit_page = client.get(f"{url}/edit")
    edited = {**_form(edit_page.text, f"{url}/edit"), **_fields_from(edit_page.text), "end_date": "2026-10-07"}
    assert _post(client, f"{url}/edit", edited) == 303

    rejected = client.post(f"{url}/confirm", data=stale, headers=ORIGIN)
    assert rejected.status_code == 409
    assert "The preview changed; review and confirm it again." in rejected.text
    assert "Confirm and submit version 2" in rejected.text
```

`tests/smoke/test_demo_ui_smoke.py`:

```python
"""The demo app starts offline from the environment and serves its first page (Issue #14)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from enterprise_employee_agent.web.server import create_app_from_env


@pytest.mark.smoke
def test_demo_app_starts_offline_from_environment(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("DEMO_DATABASE_PATH", str(tmp_path / "demo.sqlite"))
    client = TestClient(create_app_from_env())
    client.post(
        "/identity", data={"identity_id": "employee-alice"}, headers={"origin": "http://testserver"}
    )
    page = client.get("/")
    assert page.status_code == 200
    assert "offline · scripted" in page.text
    assert (tmp_path / "demo.sqlite").exists()
```

- [ ] **Step 2: Run the tests**

Run: `uv run --locked pytest tests/integration/test_demo_ui_journey.py tests/smoke/test_demo_ui_smoke.py -v`
Expected: PASS. These tests compose code that Tasks 1–6 already test, so they should pass on the first run. If one fails, treat it as a real integration defect: debug it with superpowers:systematic-debugging and fix the code, not the assertion.

Then run the full gate:
`uv run --locked pytest -q && uv run --locked pytest -m smoke -q && uv run --locked ruff check . && uv run --locked ruff format --check . && make eval-offline`
Expected: everything passes; the offline eval still reports 7/7 safety and 8/8 knowledge.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_demo_ui_journey.py tests/smoke/test_demo_ui_smoke.py
git commit -m "test: cover the full demo UI journey and offline startup"
```

- [ ] **Step 4: Manual accessibility and narrow-screen checklist**

Run `make demo` and go through the checklist in a browser. Record each result, with a note wherever something failed, in the PR body:

- [ ] Keyboard only: choose an identity, ask a scripted question, open the excerpt `<details>`, create a draft from the scripted description, confirm, switch to HR, request clarification, switch back, answer, and confirm again. Every control must be reachable, and focus must stay visible and in visual order.
- [ ] Every input has a visible label. Error messages are announced (`role="alert"`) and linked through `aria-describedby`.
- [ ] Contrast of the banner, buttons, links, and error text is at least 4.5:1 (browser devtools contrast checker).
- [ ] At a 360 px viewport there is no horizontal page scroll; tables scroll inside `.table-wrap`.
- [ ] With JavaScript disabled, the full journey still works; only the "Sending…" label is missing.
- [ ] Employee, manager (Morgan sees Alice; Riley gets 404), and HR (audit history, no drafts in the list) all look correct.
- [ ] Wording: no page implies eligibility, approval, or a real GitLab/Tilt/HRIS connection.

- [ ] **Step 5: Push and open the PR**

State: `Stage: review. Required documents: read. Next allowed action: open PR for Issue #14 and request independent QA. Merge: blocked until QA PASS and owner acceptance.`

```bash
git push -u origin feat/14-demo-ui
gh pr create --title "feat: minimal role-aware demo interface (#14)" --body-file <(cat <<'EOF'
Closes #14.

## What
Server-rendered FastAPI + Jinja2 demo over the existing domain: identity switcher, grounded questions with evidence, leave draft from free text, versioned preview and explicit confirmation, HR processing and clarification loop, role-scoped lists and projections. Spec: `docs/superpowers/specs/2026-09-22-issue-14-demo-ui-design.md`; CSRF: decision 0006; plan: `docs/superpowers/plans/2026-09-22-issue-14-demo-ui.md` (see its "Deviations from the spec").

## Closes carried-over findings
- Issue #10: `get()`/full records never reach `web/` (every read through `can_view`/`project_for`); `sqlite3.Error` → `STORAGE_UNAVAILABLE` (503); connections are closed after each call.
- Issue #13: `AssistantFailure.detail`/`error_kind` are never rendered (test with a marker).

## Verification
- `uv run --locked pytest` — <paste count>
- `uv run --locked pytest -m smoke` — <paste count>
- `ruff check` / `ruff format --check` — clean
- `make eval-offline` — <paste summary>
- Manual checklist — <paste results from Step 4>

## Known limitations
- Live mode (`OPENROUTER_API_KEY` set) has no budget guard and no live eval of the UI path; local and opt-in.
- The identity cookie is unsigned by design; this is not authentication.
- Accessibility verified manually, not by automation.
- `SENSITIVE_CONTENT_REJECTED` is mapped to 422 but still produced nowhere (unchanged from #13).

## Gates
- [ ] CI green on head
- [ ] Independent QA verdict for head `<sha>`
- [ ] Owner acceptance
- [ ] Squash merge

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)
gh issue edit 14 --remove-label in-progress --add-label review
```

Expected: the PR URL is printed and hosted CI runs `checks`. Wait for it with `gh pr checks --watch`; expected: `checks` passes.

---

## Self-review against the spec

| Spec requirement | Task |
|---|---|
| Header: identity, id, role, mode, banner, switcher | 5 (`base.html`, header tests) |
| Offline scripted fixture, `OfflineDemoProvider` LookupError → ProviderError | 2 |
| Live mode by key presence with `DECISION_MODEL`, no budget guard | 2 (test), PR limitations |
| `DemoApplication` table: `mode`, `identities`, `ask`, `propose_fields`, `create_draft`, `update_draft`, `cancel_draft`, `confirm`, `hr_start`, `hr_clarify`, `employee_clarify`, `requests_for`, `request_for` (`preview` folded in, deviation 3) | 2–4 |
| `list_requests`, `STORAGE_UNAVAILABLE` | 1 |
| Riley cannot see Alice's request; manager sees only direct reports; HR list excludes drafts; only HR gets audit history | 3, 4, 6, 7 |
| Pages and routes for employee, manager, HR; PRG except `/ask` and `/requests/propose` | 5, 6 |
| Evidence: title, source link, `<details>` excerpt; synthetic label | 4 (metadata), 5 (template, test) |
| Error table (422/404/403/303/409/503/403-CSRF/200-unavailable/500) | 5 (status table, CSRF, 500, unavailable), 6 (422, 404, 403, 409) |
| CSRF: SameSite=Strict + Origin/Referer on every POST | 5 (all POST routes tested, including Task 6 ones) |
| Idempotency key in hidden field; hidden fields never carry actor id; `actor_id` field ignored | 6 |
| Failure detail/marker never in HTML; markup escaped | 5 |
| In-flight "Sending…" script; works without JS | 5 (`base.html`), 7 (manual) |
| Integration journey and visible stale rejection | 7 |
| Smoke: offline start, `GET /` 200 with mode label | 7 |
| `make demo` on 127.0.0.1; deps via `uv add` | 5 |
| Manual accessibility/narrow-screen checklist in PR | 7 |

## Execution handoff

After the owner approves this plan: push it to `main` (docs), move Issue #14 from `draft` to `ready`, then execute in a fresh session with superpowers:subagent-driven-development (recommended) or superpowers:executing-plans.
