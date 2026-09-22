# Minimal role-aware demo interface — design

Status: approved in brainstorming 2026-09-22 (sections 1–3), awaiting owner review of this file
Related: Issue #14, decisions 0005 and 0006, `DEVELOPMENT_FRAMEWORK.md`, Issue #10 finding on
`SQLiteLeaveRepository.get()`, Issue #13 (`leave/assistant.py`)

## Goal

Expose the complete v0.1 scenario (grounded question → leave draft → preview → explicit
confirmation → HR processing → clarification loop) in a server-rendered FastAPI UI where the
selected identity, its role, the model mode, evidence, preview version, and request status are
always visible.

## Scope

In scope: FastAPI + Jinja2 server-rendered pages with minimal CSS; an identity switcher over the
six identities in `data/synthetic_protected/demo-access-v1.json`; a composition layer
(`app.py` + `DemoApplication`) over the existing domain functions; live/offline model mode;
CSRF protection (decision 0006); error, empty, and in-flight states; offline automated tests;
a manual accessibility and narrow-screen checklist in the PR.

Out of scope: SPA framework, production authentication, signed sessions, admin console, visual
design system, Playwright/axe automation, a live eval of the UI path, a budget guard for live
mode, `build_clarification_request` in the HR flow, deployment beyond `127.0.0.1`.

## Decisions taken in brainstorming

1. **Model mode by configuration.** `OPENROUTER_API_KEY` set → live `OpenRouterProvider` with
   `evals.live.DECISION_MODEL`; unset → offline mode with a scripted fixture. The header shows the
   mode. Live mode is opt-in, local, and has no budget guard (known limitation).
2. **Identity switcher.** All six identities are selectable; the choice lives in an unsigned
   cookie. Every request re-resolves it through `resolve_identity`. The switcher is the feature
   being demonstrated (e.g. Riley cannot see Alice's request), so signing adds nothing.
3. **CSRF.** Cookie `SameSite=Strict` plus an `Origin`/`Referer` check on every POST — decision
   0006.
4. **Leave fields.** Free text → `propose_leave_fields` → an editable pre-filled form; on any
   proposal failure the form is shown empty with a "fill in manually" note. Nothing is created
   from the proposal without the employee submitting the form.
5. **Architecture A.** `app.py` composes; `DemoApplication` is the only entry point for `web/`;
   `web/` contains only routes, templates, view models, and error mapping. No business rules in
   handlers.

## Pages and flows

Header on every page: selected identity (display name, id), role, model mode (`live · <model>` /
`offline · scripted`), a persistent "educational demo — not a real HR system" banner, and the
identity switcher (`POST /identity`).

Employee:

- `GET /` — question form; `POST /ask` renders the answer on the same page (no mutation, so no
  PRG). Offline mode lists the scripted questions as suggestions.
- `GET /requests/new` — free-text description; `POST /requests/propose` renders the editable form
  (start date, end date, type, comment) pre-filled from the proposal or empty on failure.
- `POST /requests` — creates the draft, then `303` to `/requests/{id}`.
- `GET /requests/{id}` — preview: payload, request version, digest; actions confirm / edit /
  cancel. Edit is `GET /requests/{id}/edit` → `POST /requests/{id}/edit`. In
  `needs_clarification` the page shows HR's question and a pre-filled form that answers it.
- `GET /requests` — the employee's own requests with status.

Manager: `GET /requests` and `GET /requests/{id}` render only `ManagerLeaveProjection` of direct
reports. No actions.

HR: `GET /requests` lists every request that has left `draft` (a list filter in
`DemoApplication.requests_for`; `can_view` is unchanged, so a draft opened by id still renders
under the normal rules); `GET /requests/{id}` renders
`HrLeaveProjection` plus the audit history; actions "start processing" and "request
clarification" (free-text question).

Common rules:

- Any request outside the actor's scope returns the same `404` page as a non-existent id.
- Every POST is followed by `303` (PRG) except `/ask` and `/requests/propose`, which render.
- Submit buttons are disabled with a "sending…" label by a small inline script; every flow works
  without JavaScript.
- Evidence: each citation shows the document title and a link to its public source from
  `data/manifest.json`, with a `<details>` excerpt of the document text. The synthetic restricted
  fixture (not in the manifest) shows its id and "internal synthetic document". Answers, guidance,
  and status texts never imply eligibility or a real GitLab/HRIS integration.

## Components and contracts

### `app.py` — composition

- `DemoSettings.from_env()`: `database_path` (default `var/demo.sqlite`), `openrouter_api_key |
  None`, `host` (default `127.0.0.1`), `port`.
- `build_demo_application(settings, *, clock=..., id_factory=...) -> DemoApplication`: loads the
  demo access manifest, the document access map, the corpus manifest (for citation metadata), and
  the prompts; selects the provider; constructs `SQLiteLeaveRepository`.
- Offline provider: `OfflineDemoProvider` wraps `ScriptedProvider` with the fixture
  `data/demo/scripted-v1.json` (2–3 grounded questions, one leave description for
  `leave-fields-v1`) and converts `LookupError` into
  `ProviderError(MALFORMED_RESPONSE, "no scripted response")`, so an unscripted question takes
  the normal unavailable path instead of crashing.
- `clock` and `id_factory` are injected so tests are deterministic.

### `DemoApplication` — the only entry point for `web/`

Every method takes `actor_id: str` from the cookie first and calls `resolve_identity` itself; no
method accepts a `DemoIdentity`. `request_id`, `event_id`, and `occurred_at` are always generated
server-side. Only `WorkflowError` escapes.

| Method | Returns | Built on |
|---|---|---|
| `mode()` | `DemoMode` (live/offline, model id) | settings |
| `identities()` | the six identities for the switcher | manifest |
| `ask(actor, question)` | `AssistantOutcome` + citation metadata | `answer_for_actor` |
| `propose_fields(actor, text)` | `FieldProposalOutcome` | `propose_leave_fields` |
| `create_draft(actor, payload, key)` | `LeaveRequestPreview` | `create_draft_from_fields` |
| `update_draft(actor, id, version, payload, key)` | `LeaveRequestPreview` | `UpdateDraftInput` + `repository.execute` |
| `cancel_draft(actor, id, version, key)` | projection | `CancelDraftInput` |
| `preview(actor, id)` | `LeaveRequestPreview` | `can_view`, then `build_leave_preview` |
| `confirm(actor, id, version, digest, key)` | projection | `ConfirmSubmitInput` with a `ConfirmationEnvelope` rebuilt from the hidden fields |
| `hr_start(actor, id, version, key)` | projection | `StartProcessingInput` |
| `hr_clarify(actor, id, version, question, key)` | projection | `RequestClarificationInput` |
| `employee_clarify(actor, id, version, payload, key)` | `LeaveRequestPreview` | `provide_clarification_from_fields` |
| `requests_for(actor)` | tuple of role projections | `list_requests` → `visible_requests` → `project_for` |
| `request_for(actor, id)` | `RequestView` (projection, audit for HR) | `project_for`, `authorize_audit_history` |

Reads never return a full `LeaveRequest` to `web/`: every read goes through `can_view` and
`project_for` (or `build_leave_preview` after `can_view`), which closes the Issue #10 finding on
`repository.get()`.

### Domain changes

- `SQLiteLeaveRepository.list_requests() -> tuple[LeaveRequest, ...]` — internal full records,
  documented like `get()`: callers must authorize and project.
- `WorkflowErrorCode.STORAGE_UNAVAILABLE` with the message "The demo storage is unavailable; try
  again." `DemoApplication` converts any `sqlite3.Error` into it.
- The repository already opens one connection per call; the application constructs it once.

### `web/` — HTTP only

- `server.py`: `create_app(demo: DemoApplication) -> FastAPI` with the routes above; a
  module-level `app` built from `DemoSettings.from_env()` for uvicorn.
- `session.py`: identity cookie `demo_identity` (`HttpOnly`, `SameSite=Strict`, `Path=/`), and
  the Origin/Referer dependency applied to every POST.
- `views.py`: flat dataclasses of display strings. The `AssistantOutcome` mapping keeps answer
  text, citations, clarifying question, and guidance; `AssistantFailure.detail`, `error_kind`,
  `violation_kind`, HTTP status codes, and schema names are never passed to templates.
- `errors.py`: `WorkflowError.code` → HTTP status and `ERROR_MESSAGES` text.
- `templates/*.html` (Jinja2, autoescape on) and one static CSS file.
- Idempotency key: `uuid4` generated when a form is rendered and carried in a hidden field. Hidden
  fields carry only the key, the expected version, and the digest — never an actor id.
- `make demo` → `uv run --locked uvicorn enterprise_employee_agent.web.server:app --host
  127.0.0.1`. Dependencies `fastapi`, `jinja2`, `uvicorn`, `python-multipart` via `uv add`.

## Error handling

| Condition | HTTP | User sees |
|---|---|---|
| `VALIDATION_FAILED`, `SENSITIVE_CONTENT_REJECTED` | 422 | the form with entered values and the message |
| `NOT_FOUND`, or `FORBIDDEN` on another person's request | 404 | one identical not-found page |
| `FORBIDDEN` for an action the role never has | 403 | "not available to the selected identity" |
| `UNAUTHORIZED` (no or unknown cookie) | 303 | cookie cleared, identity chooser |
| `VERSION_CONFLICT`, `STALE_CONFIRMATION`, `INVALID_TRANSITION` | 409 | the request page with a fresh preview and a "data changed" notice |
| `IDEMPOTENCY_CONFLICT` | 409 | the message; a same-key same-data repeat replays the stored result |
| `STORAGE_UNAVAILABLE` | 503 | generic message |
| POST without or with a foreign `Origin`/`Referer` | 403 | generic message; the domain is not called |
| model unavailable / contract violation | 200 | `/ask`: guidance to contact HR; `/requests/propose`: empty form with a note |
| any other exception | 500 | generic message; traceback only in the server log |

## Testing

All automated tests are offline on `ScriptedProvider`; TDD per `DEVELOPMENT_FRAMEWORK.md`.

- `tests/unit/app/` — `DemoApplication` on a temporary SQLite with fixed `clock`/`id_factory`:
  every method's happy path; Riley cannot see Alice's request in `request_for` or
  `requests_for`; a manager sees only direct reports; the HR list excludes drafts; only HR gets audit history; `sqlite3.Error`
  → `STORAGE_UNAVAILABLE`; provider selection by key presence; an unscripted offline question
  yields the unavailable outcome.
- `tests/unit/web/` — `TestClient` over a fake `DemoApplication`: the error table above; CSRF
  rejection without and with a foreign `Origin`; `303` after every mutating POST; the hidden
  idempotency key; a form field named `actor_id` is ignored; a failure carrying a marker in
  `detail`/`error_kind` never appears in the HTML; corpus and model text with markup is escaped.
- `tests/integration/` — real `DemoApplication` + `TestClient`: employee proposes → previews →
  confirms → HR starts → HR requests clarification → employee answers; a stale confirm is
  visibly rejected.
- `tests/smoke/` — the app starts in offline mode and `GET /` returns 200 with the offline mode
  label.
- Manual PR checklist: keyboard-only journey, labels and focus order, error association,
  contrast, 360 px width, JavaScript disabled, full journey for employee, manager, and HR.

## Acceptance mapping (Issue #14)

| Criterion | Covered by |
|---|---|
| Whole v0.1 scenario through the UI, role and state visible | integration journey, header |
| Evidence and unsupported answers understandable | citation rendering, guidance, manual checklist |
| Confirmation shows version and payload; stale rejected visibly | preview page, 409 handling, integration test |
| Manager/HR render only typed projections | `DemoApplication` read path, unit tests |
| Keyboard, labels, errors, narrow screen usable | manual checklist in PR |

## Known limitations

- Live mode has no budget guard and no live eval of the UI path; it is local and opt-in.
- The identity cookie is unsigned by design; this is not authentication.
- Accessibility is verified manually, not by automation.
