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
- Issue #9 (authorization and role projections) is integrated into `main` by PR #24: new
  `leave/access_policy.py`
  (`resolve_identity`, `can_view`, `visible_requests`, `authorize_command`, `authorize_replay`,
  `authorize_audit_history`, `project_for`) and a new immutable `LeaveRequest` entity in
  `leave/contracts.py`, plus `WorkflowError`. `retrieval.retrieve_for_identity()` is now the only
  retrieval path `answer_question()` calls — it takes a resolved `DemoIdentity`, and
  `answer_question`'s public parameter changed from a bare `role: ActorRole` to `identity:
  DemoIdentity` (all three call sites — offline eval, live eval, tests — updated).
  Independent review (code-reviewer agent) found and this round fixed two blockers: (1) every
  policy entry point now calls `_verify_bound()`, rejecting a hand-built `DemoIdentity` that
  does not exactly match the manifest's declared entry for that `identity_id` — without it a
  forged identity got another employee's HR projection; (2) `retrieve(question, role, ...)` was
  still the de facto production path via `answer_question`, so it is fully retired from
  production code now (`retrieve_for_identity` is the only caller). Also strengthened per review:
  `_score_role_view` compares the exact `ROLE_PROJECTION_FIELDS` key set per role, not just field
  values; `_score_forbidden_disclosure` asserts a real secret string is absent from the
  manager's serialized JSON. Independent re-review approved the fixes; PR #24 was squash-merged
  as `980b2c6`, Issue #9 is closed, and `main` is verified. 256/256 tests pass, ruff/format clean,
  offline eval remains 7/7 safety + 8/8 knowledge. Non-blocking follow-ups are tracked in #25.
- Issue #10 (SQLite persistence) passed independent QA on 2026-09-21: adversarial probes
  (process kill mid-transaction, cross-process optimistic-concurrency race, restart, append-only
  triggers) all confirmed the claimed guarantees. Verdict PASS. PR #26 squash-merged as
  `97a29ab`; Issue #10 closed; `main` re-verified (279/279 tests). Five non-blocking findings
  from the review were filed as acceptance criteria rather than fixed inline: `CONFIRM_SUBMIT`
  does not yet validate `ConfirmationEnvelope.payload_digest` against the stored payload (→
  Issue #11 — note: a blanket reject-all-`CONFIRM_SUBMIT` guard is wrong, it breaks
  `test_update_and_every_declared_transition_are_persisted`; the fix must be digest validation
  mapped to `WorkflowErrorCode.STALE_CONFIRMATION`); `get()` and `execute()` return
  un-authorized/un-projected full records, safe only because no public caller exists yet (→
  Issue #14); raw `sqlite3` exceptions and unclosed connections are unsafe under a live server (→
  Issue #14, before FastAPI is wired up).
- No HTTP/UI or external integration exists yet; the frozen corpus and local workflow remain
  offline.

## 7. Next steps

1. Implement version-bound confirmation, idempotency, and the fake-adapter vertical slice in
   Issue #11, calling `access_policy` rather than re-deriving access (D1/D2), and closing the
   `payload_digest` validation gap carried over from the #10 review.
2. Integrate the knowledge and workflow paths, then build a server-rendered FastAPI interface
   with minimal CSS and no SPA framework, applying `project_for` to every response per the
   authorization findings carried over from #10 into Issue #14.
3. Complete Docker Compose, offline CI, README, and clean-clone verification.
4. Expand the dataset and run the held-out live evaluation; publish the v0.1 results, failures,
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
