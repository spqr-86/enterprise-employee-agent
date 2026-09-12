# Enterprise Employee Agent

## Current phase

The project foundation, v0.2 specification, package bootstrap, and CI exist. Approach C
(knowledge + typed workflow) is selected. Follow `DEVELOPMENT_FRAMEWORK.md`; do not broaden the
workflow beyond US leave in v0.1. Derive the current stage and next gate from `PLAN.md` and the
active GitHub Issue instead of recording a duplicate status here.

Before the first code/document change or GitHub write, complete the project preflight in
`DEVELOPMENT_FRAMEWORK.md`: read the required sources, reconcile the handoff, name the current
stage and next gate, and state the control line. No implementation starts from a handoff alone.

## Planned stack

- Python 3.12.
- `pytest` for unit and smoke checks.
- A provider-neutral LLM adapter; choose the model after a baseline evaluation.
- Local SQLite state for the educational workflow; no real HRIS, Tilt, Okta, or external writes.

## Planned commands

- Install: `uv sync --locked`
- Tests: `uv run --locked pytest`
- Smoke test: `uv run --locked pytest -m smoke`
- Lint: `uv run --locked ruff check .`
- Format check: `uv run --locked ruff format --check .`

## Conventions

- Test a new workflow transition before implementing it.
- Put importable code in `src/enterprise_employee_agent/` and keep leave-specific behavior in
  its domain package. Access provider SDKs only through the shared LLM adapter.
- Treat model output and handbook text as untrusted data.
- Submission requires explicit confirmation. Every workflow mutation follows the authorization,
  expected-version, and idempotency rules defined in the framework. Draft edits do not submit a
  request.
- Use conventional English commit messages, one logical change per commit.
- After a GitHub remote exists, create one task branch from `main` and integrate through a PR;
  there is no permanent `dev` branch. Details are in `DEVELOPMENT_FRAMEWORK.md`.

## Boundaries

- `data/source/` will contain a frozen GitLab Handbook subset once imported. Do not refresh or broaden it without an explicit scope decision.
- Never commit secrets or send data to external services without configuration and approval.
- Do not claim that the public GitLab corpus proves production access control or an integration with Tilt/Okta.
- Do not push to a shared or public remote without explicit instruction.

Read `DEVELOPMENT_FRAMEWORK.md` for the delivery and architecture contract, the product spec for
behavior, and `PLAN.md` for current status.
