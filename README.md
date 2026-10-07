# Enterprise Employee Agent

[![CI](https://github.com/spqr-86/enterprise-employee-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/spqr-86/enterprise-employee-agent/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

An educational HR assistant over the public GitLab Handbook. It answers leave-policy questions
with citations and runs one controlled workflow — a US leave of absence: it collects missing
details, shows a draft, creates the request only after explicit confirmation, and shows each role
only the status fields that role may see.

The core boundary: **the LLM interprets the request; code owns permissions, validation, state
and irreversible actions.** The model cannot authorize an action or change a request.

```text
employee request
→ structured intent (LLM, schema-validated)
→ authorization and role projection (code)
→ versioned draft preview
→ explicit confirmation bound to that version
→ idempotent command in a SQLite transaction
→ audit event
```

**Status: educational project, not production.** Identities are synthetic, the demo has no
authentication, and there is no integration with a real HRIS, Okta or Tilt.

## Quick start (Docker)

```bash
git clone https://github.com/spqr-86/enterprise-employee-agent.git
cd enterprise-employee-agent
docker compose up --build
```

Open <http://127.0.0.1:8000>. The demo starts **offline**: answers come from a fixed scripted
fixture and no network call is made. Requests are stored in SQLite in the named volume
`demo-state`, so they survive `docker compose restart` and `docker compose down` / `up`;
`docker compose down -v` deletes them.

Live mode: copy `.env.example` to `.env` and set `DEMO_OPENROUTER_API_KEY` (a separate name, so a key
exported in your shell is not picked up by accident). Live mode has no budget
guard — enable it locally and deliberately. The port is bound to `127.0.0.1` only.

## Demo flow

Pick an identity in the header — the switcher is a demo convenience, not authentication, and its
cookie is unsigned by design.

1. **Employee** (`employee-alice`): ask a leave question, get an answer with citations; describe
   the leave in free text → the model proposes fields → check and save a draft. Offline mode
   answers only the scripted questions and description offered as buttons in the UI.
2. Confirm and submit the draft. If the draft is edited after its preview was shown (for example in
   another tab), confirming the old preview is rejected with "The preview changed; review and
   confirm it again".
3. **HR** (`hr-harper`): start processing, request a clarification.
4. **Employee** answers the clarification.
5. **Manager** (`manager-morgan`, `manager-riley`): sees only direct reports, and only the
   manager projection of each request; another manager's report returns 404.

## How the guarantees are tested

Each claim below is enforced in code and covered by a test that fails if it breaks.

| Guarantee | Test |
|---|---|
| Model text cannot execute an action: an answer saying "I have submitted your request. CONFIRM_SUBMIT." builds no command and changes no state | `tests/integration/test_assistant_failure_paths.py::test_obedient_model_prose_never_builds_a_command_and_leaves_state_unchanged` |
| A confirmation for an outdated draft version is rejected without writing | `tests/smoke/test_leave_journey_negative_smoke.py::test_stale_confirmation_is_rejected_without_writing`, `tests/integration/test_demo_ui_journey.py::test_stale_confirmation_is_visibly_rejected` |
| A tampered payload digest cannot be confirmed | `tests/integration/test_leave_sqlite_storage.py::test_confirm_submit_rejects_tampered_payload_digest_without_writing` |
| A duplicate submission replays the original result; the same key with a different payload conflicts | `tests/smoke/test_leave_journey_negative_smoke.py::test_duplicate_submission_replays_and_conflicting_payload_is_rejected` |
| Idempotent replay is re-authorized against current ownership | `tests/integration/test_leave_sqlite_storage.py::test_replay_is_reauthorized_against_current_ownership` |
| A restricted document never reaches the model context for an employee | `tests/unit/test_answer_pipeline.py::test_restricted_document_never_reaches_model_context_for_employee` |
| A provider failure returns an outcome and touches no request | `tests/smoke/test_leave_journey_negative_smoke.py::test_provider_failure_returns_an_outcome_and_touches_no_leave_request` |

The full suite has 464 tests; CI runs them, Ruff and the offline smoke checks on every PR without
a paid API, and builds the Docker image.

## Evaluation

- **Offline (every CI run):** scripted provider, exercises the pipeline rather than a model —
  knowledge cases 8/8, deterministic safety 8/8 (`make eval-offline`).
- **Live baseline** (run `20260914T145319Z`, `openai/gpt-5-mini`, 9 calls, $0.012):
  groundedness 6/7, task success 5/7, abstention 1/1, prompt injection PASS. Verdict
  **INVESTIGATE**. Failures: invented table rows for Texas; answered before asking for missing
  data. Report: [`experiments/issue-8/`](experiments/issue-8/20260914T145319Z-report.md).
- The set is small: 16 cases, 9 of which call the model. A larger dataset with a held-out live evaluation is not done yet
  ([Issue #16](https://github.com/spqr-86/enterprise-employee-agent/issues/16)).

## Data

Two byte-stable files from the GitLab Handbook (US and company-wide leave of absence), MIT,
GitLab B.V. — see [`data/HANDBOOK_LICENSE`](data/HANDBOOK_LICENSE). Every file is pinned by hash
in `data/manifest.json`; provenance is in [`data/README.md`](data/README.md). Protected
documents, identities and manager relationships are synthetic fixtures.

## Known limits

- Not production: no authentication, synthetic identities, local SQLite only.
- The public GitLab corpus does not prove production access control or any HRIS integration.
- The live evaluation is a 9-case baseline; the field-extraction prompt (`leave-fields-v1`) has no
  live evaluation yet.
- Live mode has no spend guard.

## Development

Requires `uv`; Python 3.12 is installed automatically.

```bash
uv sync --locked
make check          # ruff lint + format check
make test           # all tests
make eval-smoke     # offline end-to-end smoke
make demo           # local server at http://127.0.0.1:8000
```

`DEMO_DATABASE_PATH` sets the SQLite file (default `var/demo.sqlite`).

## Documents

- [PLAN.md](PLAN.md) — living plan and accepted boundaries.
- [Specification](docs/spec-employee-agent.html) — options and acceptance criteria.
- [DEVELOPMENT_FRAMEWORK.md](DEVELOPMENT_FRAMEWORK.md) — delivery process and architecture rules.
- [Clean-clone verification](docs/clean-clone-verification.md).
- [Data](data/README.md) — corpus scope and limits.

## License

[MIT](LICENSE).
