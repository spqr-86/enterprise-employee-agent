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
- Private GitHub remote configured: `spqr-86/enterprise-employee-agent`; local `main` tracks
  `origin/main`.
- Existing GitLab corpus located and assessed; no data copied yet.
- Product spec v0.2 written; approach C, US-only v0.1, and a read-only manager view are selected.
- Bootstrap is integrated into `main`: Python 3.12 package metadata, `uv.lock`, an import smoke
  test, Ruff/pytest Make targets, and minimal read-only GitHub Actions CI.
- Local locked install, checks, tests, smoke test, sdist, and wheel pass. GitHub Issue #1 is
  closed; PR #2 passed hosted CI and was merged on 2026-09-12.
- Process hardening from PR #4 is integrated and Issue #3 is complete: preflight, Issue/PR
  templates, lifecycle labels, squash-only merge, and a private-repository manual gate fallback.
- Full v0.1 grooming created milestone `v0.1` and dependency-linked Issues #5–#16. Issues #5 and
  #6 are Ready; later Issues remain Draft until their declared dependencies exist.
- Issue #5 imported the minimal company-wide and US leave-of-absence subset into `data/source/`
  with a provenance manifest, a deterministic validator, and tests; PR #19 is integrated and
  Issue #5 is complete.
- Issue #6 implementation defines the versioned leave contract, synthetic identities and
  permission manifest, typed command/confirmation/audit boundaries, exact role projections,
  state transitions, errors, and consistency tests. PR #20 passed independent QA and was accepted
  and squash-merged as `4d6002e` on 2026-09-13; Issue #6 is complete and `main` is verified (21
  unit tests pass).
- Issue #7 (micro-eval dataset) is integrated into `main` and Issue #7 is closed: pydantic
  discriminated-union case schema, dataset validator, scorer, text reporting, the versioned
  `evals/cases/v0.1.yaml` (14 cases transcribed from the draft), and a `run.py` CLI wired against
  the real Issue #6 workflow contracts for 5 of 6 safety/workflow categories (`provider_failure`
  is a documented placeholder pending Issue #8's LLM adapter). Decided: no sub-document chunking
  for v0.1, whole-document evidence IDs only (`docs/decisions/0001-v0.1-evidence-granularity.md`).
  59/59 tests pass, ruff clean. Known limitations parked as backlog (not blocking): one-sided
  safety checks lack negative controls, a category-name typo produces misleading validation
  errors, `_REPO_ROOT` path resolution assumes an editable install, `abstain_expected` with
  non-empty `expected_evidence` is silently accepted, no `make eval` target/README pointer, and
  the `expects_clarification` field is metadata-only (not yet scored).
- Issue #8 baseline pipeline (lexical k=1 retrieval, OpenRouter answer contract, budgeted live
  runner, review and decision CLIs) is built on `feat/8-retrieval-answer-baseline`. Live run
  `20260914T145319Z`: complete, 18 calls, $0.024; verdict **INVESTIGATE** — groundedness 6/7,
  task success 5/7, abstention 1/1, prompt injection PASS, deterministic safety 6/6. Failures:
  invented Texas table rows; answered before clarifying on missing data. Recorded as known v0.1
  limitations; report `experiments/issue-8/20260914T145319Z-report.md`. PR #22 passed independent
  QA, was accepted and squash-merged as `2652d3e` on 2026-09-14; Issue #8 is closed and `main` is
  verified (222 tests).
- Issue #9 (authorization and role projections) is groomed and Ready; owner decisions D1–D3 are
  recorded in the Issue.
- No product behavior or external integration exists; the frozen corpus is imported and
  validated offline.

## 7. Next steps

1. Implement Issue #9 (authorization policy and role projections). The two Issue #8 baseline
   failures stay known limitations; prompt fixes and a rerun belong to Issue #13, which adds
   retry/repair per decision 0004.
2. Test and implement version-bound confirmation, idempotency, workflow
   transitions, persistence, and the fake-adapter vertical slice.
3. Integrate the knowledge and workflow paths, then build a server-rendered FastAPI interface
   with minimal CSS and no SPA framework.
4. Complete Docker Compose, offline CI, README, and clean-clone verification.
5. Expand the dataset and run the held-out live evaluation; publish the v0.1 results, failures,
   limits, and release decision.

## 8. Open decisions

- Resolved in Issue #8 (2026-09-14): live provider OpenRouter; decision model
  `openai/gpt-5-mini` (`reasoning: {"effort": "low"}`), comparison model `deepseek/deepseek-v3.2`
  (`temperature: 0`); evaluation spend capped at $0.50 cumulative for Issue #8.

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
