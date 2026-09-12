# Enterprise Employee Agent — plan

## 0. Constitution

- The v1 corpus is a frozen, public GitLab Handbook HR subset; source changes require a deliberate data-scope decision.
- The product scope is one end-to-end leave-of-absence workflow, not a universal enterprise automation platform.
- The workflow uses local educational state and must never present itself as Tilt, Okta, or GitLab production infrastructure.
- Access decisions are enforced before retrieval and again before rendering role-specific results.
- Submission is prepared, previewed, explicitly confirmed, version-bound, and idempotent before
  it changes the request to `submitted`; every workflow mutation is authorized and idempotent.
- New workflow transitions begin with tests; model-dependent outcomes are evaluated by outcome category rather than exact prose.
- No secrets enter version control; no remote push or external write occurs without an explicit instruction.

## 1. Goal

Build a demonstrable corporate assistant that grounds HR answers in GitLab Handbook documents and completes a bounded leave-of-absence workflow. An employee can ask what applies, provide missing details, review a request, submit it to a local learning service, and see its status. A manager has a read-only view of the minimum operational information; HR sees the details needed to process the request and can request clarification.

## 2. Data and inputs

The planned source is the existing frozen 47-file GitLab Handbook HR subset, documented in `data/README.md`. The first slice is the company-wide and US leave-of-absence material. A local fixture set supplies identities, roles, request state, and a clearly labelled demonstration permission manifest.

## 3. Architecture

The selected architecture is a typed workflow, not a free-running planner:

`user request -> allowed-document retrieval -> fact extraction -> clarification or preview -> explicit confirmation -> idempotent local request write -> role-specific status view`

Importable code will live in `src/enterprise_employee_agent/`, grouped by responsibility:
`access`, `knowledge`, `leave`, `llm`, `storage`, and `web`. Retrieval, policy interpretation,
state transition, persistence, and rendering remain separately testable. The detailed boundaries
and target tree are defined in `DEVELOPMENT_FRAMEWORK.md`.

The reusable boundaries in v0.1 are the LLM adapter, evidence contract, authorization policy
interface, version-bound confirmation envelope, idempotent command handling, audit events, and
eval result format. Leave fields, prompts, transitions, and role projections remain
domain-specific until a second workflow demonstrates a real shared abstraction.

The minimum state machine is `draft -> submitted -> processing`, `draft -> cancelled`, and
`submitted -> needs_clarification -> submitted`. A manager has a read-only, minimum-data view
in v0.1. The selected public source does not establish a manager approval transition.

## 4. Why this is useful

Most document chat demos stop at an answer. This one makes the boundary visible: the employee gets only allowed handbook evidence, a sensitive request is represented differently for employee, manager, and HR, and the agent performs one safe, auditable action only after confirmation.

## 5. Verification and evaluation

- Unit tests for visibility projections, workflow transitions, validation, and idempotency.
- Smoke test covering question -> clarification -> versioned preview -> confirmation -> submitted request -> HR processing -> employee and manager status.
- Start with 10-15 reviewed micro-eval cases before model-dependent behavior; expand to roughly
  30-40 cases with a held-out subset before the v0.1 release.
- Evaluation categories: retrieval Recall@k, groundedness, abstention, task success, deterministic safety invariants, and operational cost/latency/error data.
- Initial quality threshold: at least 90% in each main quality category; deterministic authorization, confirmation, transition, and idempotency checks must all pass.
- Evaluation cases include unknown jurisdiction, unsupported eligibility facts, synthetic forbidden disclosure, prompt injection, stale confirmation, duplicate submission, and role-specific views.
- Every generated answer must cite an allowed handbook fragment or state that the source cannot establish the answer.
- The live baseline records model id and parameters, prompt version, corpus manifest, raw results, percentages, and absolute counts. A threshold changed after baseline must retain a written reason.

## 6. Current status

- Project foundation created on 2026-09-12.
- Existing GitLab corpus located and assessed; no data copied yet.
- Product spec v0.2 written; approach C, US-only v0.1, and a read-only manager view are selected.
- No application code or external integration exists.

## 7. Next steps

1. Reconcile the project documents and bootstrap the installable package, locked environment,
   first test, and minimal CI.
2. Import only the minimal US leave subset and record source revision, URL, retrieval date,
   licence, hashes, and stable fragment IDs.
3. Define demo identities, field-level projections, commands, state machine, error behavior, and
   10-15 reviewed micro-eval cases.
4. Build the simplest retrieval/answer baseline and publish its first error table.
5. Test and implement authorization, version-bound confirmation, idempotency, workflow
   transitions, persistence, and the fake-adapter vertical slice.
6. Integrate the knowledge and workflow paths, then complete the interface, Docker Compose, CI,
   README, and clean-clone verification.
7. Expand the dataset and run the held-out live evaluation; publish the v0.1 results and limits.

## 8. Open decisions

- Which LLM provider and model form the first retrieval/extraction baseline.
- Which minimal user interface best demonstrates the full workflow without hiding evidence,
  identity, confirmation version, and status.

## 9. Target structure

See `DEVELOPMENT_FRAMEWORK.md`. The package uses `src/enterprise_employee_agent/`; evaluation,
tests, corpus data, experiments, and project documentation remain top-level support areas.

## 10. Definition of done for v0.1

- [ ] `pytest` passes.
- [ ] `pytest -m smoke` demonstrates the full employee-to-manager flow.
- [ ] Retrieval never sends a prohibited document fragment to the model.
- [ ] The same request has correct employee, manager, and HR projections.
- [ ] Submission requires explicit confirmation and is idempotent.
- [ ] Answers cite allowed source material; unsupported eligibility is escalated.
- [ ] A stale confirmation cannot submit a changed draft.
- [ ] A reproducible live baseline and held-out report include raw failures and operating metrics.
- [ ] Docker Compose starts the application with persistent local state.
- [ ] CI runs format, lint, unit, integration, and offline smoke checks without a paid API.
- [ ] `README.md` documents setup, demo flow, architecture, eval results, data licence, local-only workflow, and known limits.
- [ ] A clean clone can be launched by following the README without undocumented steps.
