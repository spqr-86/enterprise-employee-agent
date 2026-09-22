# History

## 2026-09-12

- Created the project foundation and draft specification.
- Chose GitLab Handbook HR leave-of-absence material as the candidate v1 corpus.
- No source data or application code has been imported yet.
- Selected Approach C for US-only v0.1: typed local leave workflow, manager read-only, and HR
  processing/clarification actions.
- Added the adapted development framework, local backlog, and aligned the plan, specification,
  README, and agent context. The first work item is package/CI bootstrap.
- Created the private GitHub repository `spqr-86/enterprise-employee-agent` and pushed `main`.
- Bootstrapped an installable Python 3.12 package with a locked `uv` environment, Ruff, pytest,
  Make targets, an offline import smoke test, and minimal read-only GitHub Actions CI.
- Verified locked install, lint, format, tests, smoke test, sdist, and wheel locally. Created
  GitHub Issue #1 and pushed `chore/1-bootstrap`; the pull request and hosted CI remain next.
- PR #2 passed hosted CI and was merged into `main`; Issue #1 closed automatically. The local
  `main` was fast-forwarded to the verified remote result.
- Decided to groom the complete v0.1 backlog before creating the remaining milestone and Issues,
  then implement one Ready Issue at a time.
- PR #2 used a merge commit instead of the framework's required squash merge. The integrated
  history remains as-is; future task PRs must use squash merge.
- Opened Issue #3 and draft PR #4 to harden delivery gates. The branch adds mandatory project
  preflight, handoff reconciliation, a Ready Issue form, a PR gate checklist, and lifecycle labels.
- GitHub CI passed for PR #4 head `653424c`. Repository settings now allow squash merge only and
  delete merged branches. Technical protection of private `main` is unavailable on the current
  GitHub Free plan; the framework records a manual gate fallback pending an owner choice.
- The owner selected the private-repository option on 2026-09-12. Until the hosting plan changes,
  the integrator must manually verify the current CI result, independent QA, owner acceptance,
  squash merge, and the post-merge state of `main`.
- PR #4 passed independent QA and CI, was accepted, and was squash-merged as `1b623d0`; Issue #3
  closed. Full v0.1 grooming then created milestone `v0.1` and Issues #5–#16 with explicit
  dependencies. Only #5 and #6 are Ready; #5 is the next implementation task.
- Issue #5 imported the minimal company-wide and US leave-of-absence subset (two byte-stable
  Markdown files) into `data/source/` and recorded provenance, licence, SHA-256, byte size, and
  stable IDs in `data/manifest.json`. Added a deterministic corpus validator with a CLI
  (`make check-corpus`) and unit tests for missing, extra, hash/byte-mismatched, duplicate, and
  path-traversal cases; `data/README.md` documents selection, revision, refresh boundary, and
  reproduction.
- PR #19 passed CI and independent QA, received owner acceptance, and was squash-merged as
  `4ac5544`; Issue #5 closed and the integrated `main` passed corpus, lint, format, unit, and
  smoke checks.
- Issue #6 implementation added the v0.1 leave workflow contract, validated synthetic identities
  and role permissions, command-specific client inputs, server-bound identity context,
  request/version/payload confirmation, idempotency fingerprints, audit invariants, independent
  role projections, and security regression tests. Adversarial review initially found replay,
  fail-open access, identity spoofing, projection leakage, and audit/idempotency weaknesses; all
  reproducible Critical/High findings were fixed and the final adversarial verdict was PASS.
- PR #20 contains this Issue #6 implementation; CI, adversarial review, and independent QA are
  PASS for head `b197547`. It is awaiting owner acceptance and squash merge.

## 2026-09-13

- Owner accepted PR #20; squash-merged as `4d6002e`, task branch deleted, Issue #6 closed
  automatically. Post-merge `main` verified: 21 unit tests pass.
- Drafted the content half of Issue #7 ahead of its schema/validator/scorer code: 14 micro-eval
  cases in `evals/cases/draft-v0.1-micro-eval.md` (not yet a versioned artifact), covering normal
  questions, missing data, unsupported eligibility, out-of-corpus jurisdiction (abstain), prompt
  injection, forbidden disclosure, stale confirmation, duplicate submission, provider failure,
  and role views. 8 of the 14 cases exercise the Issue #6 workflow/authorization logic directly
  and are gradeable without a retrieval baseline.
- Open decision before writing the Issue #7 schema: the corpus has no sub-document chunking
  (`chunking_version: none-v1`, two whole-document fragments). Needs an explicit choice between
  adding real chunking for Recall@k, or keeping whole-document evidence IDs for v0.1 and scoring
  "cited the right document" only. Not yet decided.
- Decided: v0.1 keeps whole-document evidence IDs, no sub-document chunking. Recorded in
  `docs/decisions/0001-v0.1-evidence-granularity.md`. Checked against Issue #7's acceptance
  criteria — no conflict, since `chunking_version: none-v1` makes "fragment ID" equal to
  document ID at this version.
- Ran the architectural-path brainstorming for Issue #7's schema/validator/scorer design.
  Approved design recorded in
  `docs/superpowers/specs/2026-09-13-micro-eval-dataset-design.md`: pydantic discriminated-union
  case schema (`src/enterprise_employee_agent/evals/schema.py`, following the `ContractModel`
  convention in `leave/contracts.py`), a dataset-level validator, a scorer that keeps
  deterministic safety/workflow outcomes (pass/fail) strictly separate from percentage-based
  knowledge metrics (Recall@k/groundedness/abstention), and a `held_out` schema field reserved
  for a future partition policy (not applied yet — all 14 cases stay open). Next: `writing-plans`
  then TDD implementation.
- Wrote the Issue #7 implementation plan:
  `docs/superpowers/plans/2026-09-13-micro-eval-implementation.md`. 7 TDD tasks: add PyYAML →
  `evals/schema.py` → `evals/validator.py` → `evals/scorer.py` → `evals/reporting.py` →
  `evals/cases/v0.1.yaml` (14 cases transcribed from the draft into the new schema) →
  `evals/run.py`. Design decision made while planning `run.py` (flagged for review, not a
  blocker): of the 6 safety/workflow categories, only `stale_confirmation` and
  `duplicate_submission` exercise `leave/contracts.py` end-to-end; `prompt_injection`,
  `forbidden_disclosure`, and `role_view` run against the already-loaded demo access manifest
  (`data/synthetic_protected/demo-access-v1.json`) and `ROLE_PROJECTION_FIELDS`, since no live
  request-viewing service exists yet; `provider_failure` has no LLM adapter to call (Issue #8)
  and is scored against a fixed placeholder outcome, clearly commented as such. Not yet executed
  — Petr was asked subagent-driven vs. inline, no answer yet when the session was saved.
- Petr chose subagent-driven-development. Executed all 7 tasks of the Issue #7 implementation
  plan on worktree branch `worktree-issue-7-micro-eval-dataset` (base `8aaa8ab`): PyYAML dep →
  `evals/schema.py` → `evals/validator.py` → `evals/scorer.py` → `evals/reporting.py` →
  `evals/cases/v0.1.yaml` (14 cases) → `evals/run.py` CLI. Each task got a fresh implementer +
  independent task review; Task 7's review found 3 of the plan's own literal safety-scoring
  functions were tautological/dead-code despite matching the plan verbatim — a plan defect, not
  implementer error: `_score_duplicate_submission` proved `f(x)==f(x)` (same idempotency_key both
  calls, never exercised `command_fingerprint`'s deliberate key-exclusion), `_score_prompt_injection`
  had an unreachable branch (the demo manifest's own validator guarantees the condition it checks)
  and measured access-denial-fixture completeness rather than injection resistance, and
  `_score_role_view` compared identical literals built from one shared dict. Ruled to fix
  `duplicate_submission` for real (two different idempotency keys) and honestly comment the other
  two as placeholders rather than fake logic — re-review confirmed all addressed, no new breakage.
  Final whole-branch review (opus) then found 1 Critical (CI red: ruff lint/format failures) + 4
  Important (knowledge report showed stub-derived 100% scores with no marker distinguishing them
  from a real agent measurement; `expects_clarification` field declared and set but never read
  anywhere — dead field; report category ordering was nondeterministic across process runs
  because it iterated a `frozenset` of `StrEnum` members; `main()` returned exit 0 even when the
  deterministic-safety section showed FAIL, so no script could detect a safety failure without
  scraping stdout). Fixed all five in one pass (no second fix wave, per process): lint/format
  clean, stub marker added to the report header, `expects_clarification` documented as v0.1
  metadata-only, deterministic enum-declaration-order iteration, and a distinct exit code (2) for
  a safety failure vs. 1 for dataset validation failure. Re-review: all addressed, no new
  breakage. End state: 59/59 tests passing, ruff clean, 9 commits ahead of main. 6 Minor findings
  from the final review parked as backlog, not blocking (one-sided safety checks lack negative
  controls, a category-name typo produces misleading validation errors, `_REPO_ROOT` path
  resolution breaks under a non-editable install, `abstain_expected` with non-empty
  `expected_evidence` is silently accepted rather than rejected, no `make eval` target or README
  pointer to the new CLI, and the `out-of-scope-texas-detail` case's "abstain beyond the table"
  nuance from the source draft isn't machine-captured in the schema). Also noted: the plan's own
  Task 6 mapping table has a wording inconsistency ("both docs" vs. the authoritative YAML/draft
  giving only `us.md`) — a plan-text typo, not a dataset bug; the implementer correctly followed
  the YAML. Asked Petr how to integrate the branch (merge/PR/keep) — awaiting answer when this
  sync ran.
- Petr chose push+PR (consistent with #6/#20 pattern, own private GitHub repo). Pushed branch,
  opened PR #21 ("closes #7"), CI green, merged via squash 2026-09-13. Branch and worktree
  deleted (worktree removed, local branch deleted, remote branch auto-deleted by squash-merge).
  main fast-forwarded to `05b3d73`; 59/59 tests pass on merged main. Next project step: Issue #8
  (measured retrieval and answer baseline) — no plan drafted yet.
- Started Issue #8. Reviewed money available for a live baseline: OpenAI account is empty
  (429), OpenRouter has $1.71 left (shared with the fast-agent/delegate projects), no direct
  Anthropic key outside the subscription. Researched OpenRouter pricing; agreed with the owner
  on GPT-5 mini ($0.25/$2.00 per 1M tokens) as the primary baseline model and DeepSeek V3.2
  ($0.28/$0.40) as a second comparison model, estimated at ~$0.03 total for both runs against the
  14-case v0.1 dataset — far under the $1.71 balance. Declined `:free`-tier models as unstable
  for a reproducible baseline. Classified the work as architectural (new LLM adapter + retrieval,
  changes the `EvalReport`/`run.py` interface other code depends on) and started the
  `superpowers:brainstorming` flow: read Issue #8's acceptance criteria, decision
  `0001-v0.1-evidence-granularity` (v0.1 evidence is whole-document, corpus has only 2
  documents), and the current placeholder scorers in `evals/run.py` that #8 must replace. Asked
  the owner the first design question (real tiny lexical-ranker over the 2 documents vs.
  hardcoding "return both") — session saved before an answer arrived; continues in the next
  session from that question.
- Completed the Issue #8 brainstorming, continuing from the retrieval question. Corrected an
  initial misjudgment: the two-document corpus looked too small for a real ranker to matter, but
  every one of the 14 v0.1 eval cases cites only `us.md` as evidence, never `_index.md` — the
  corpus is topically asymmetric, so a lexical keyword-overlap ranker has genuine signal to
  discriminate on. Decided: overlap ranker over all corpus documents, fixed `k=1`, empty result
  (zero overlap everywhere) forces abstention rather than an arbitrary fallback document. Also
  decided: `httpx` (not the `openai` SDK) for the OpenRouter HTTP client, keeping the adapter
  provider-neutral in shape; a hard $0.50 per-run budget-guard ceiling (~16x the expected $0.03
  cost); a single committed fixture file `evals/fixtures/v0.1-live.json` recorded from one live
  run, backing all offline/CI tests through a fake adapter; and `expects_clarification` stays
  metadata-only in v0.1 (only 1 of 14 cases uses it, detecting it reliably is a separate
  nontrivial problem, already a known limitation from Issue #7). Wrote and committed the design
  spec: `docs/superpowers/specs/2026-09-13-retrieval-answer-baseline-design.md` (commit
  `d7476ba`). Next: owner reviews the spec, then `writing-plans` for the implementation plan.
- Put the Issue #8 spec through three independent reviews and rewrote it to revision 3 (draft).
  Codex found the spec silently narrowed Issue #8's chunking scope and wrongly credited Issue #6
  with document authorization (decision 0002 makes the chunking deferral explicit). A second
  review (gpt-5.6-sol) found a 14/15 case-count mismatch introduced by the first fix, no
  live/offline topology, and no rule for which of two models carries the decision. An adversarial
  review then showed Recall@1 is 7/7 for a constant "always us.md" ranker, so the k=1
  justification was false (decision 0003: Recall@1 reported with that control, not
  decision-bearing). Revision 3: restricted fixture in `data/synthetic_protected/` (a provenance-
  less manifest entry would raise `CorpusError`), answered/abstained/escalated contract,
  prompt-injection mapping, KEEP/REVERT/INVESTIGATE rule tied to framework thresholds, cumulative
  $0.50 budget, run artifact in `experiments/issue-8/` separate from hand-written offline
  fixtures, 9 cases × 2 models live. Groundedness and task success rely on owner manual review.
  Commit `298539b`. Next: owner reviews revision 3, then `writing-plans`.
- Owner approved Issue #8 spec revision 3. Wrote the implementation plan
  `docs/superpowers/plans/2026-09-13-retrieval-answer-baseline-implementation.md` (14 TDD tasks,
  from branch/spec approval through the gated paid run and PR). Verified before writing: spec
  retrieval numbers, a forbidden-document probe that ranks the HR-only fixture first without the
  filter (10 vs 8 vs 4), and current OpenRouter model IDs/prices (`openai/gpt-5-mini` accepts no
  `temperature`; expected run cost ≈ $0.08, not ≈ $0.03). Open for the owner: framework §10
  retry/repair vs the spec's no-retry rule, and the execution mode.
- An external review (gpt-6-astra) of the Issue #8 plan found five gaps, all verified against the
  plan, spec and framework: the comparison model would show groundedness and task success 0/7
  for missing reviews; the report checked only committed git changes and never compared recorded
  hashes; the full provider body (possibly with hidden reasoning) went into the artifact; the
  JSON Schema was hand-written next to the Python model; and the retry/repair exception lived only
  in a future report. Owner chose: comparison model reported as `not reviewed` (no extra manual
  review), and approved all fixes. Plan and spec revised: generated schema, response field
  allowlist with a reasoning fixture, `source_changed_since` covering uncommitted/untracked
  changes plus `run_input_mismatches`, and decision 0004 (no retry/repair in the baseline, §10
  applies from Issue #13). Owner also accepted the ≈ $0.08 run cost and chose subagent-driven
  execution. Next: execute the plan from Task 0.
- 2026-09-14: Executed the Issue #8 plan with subagent-driven development on
  `feat/8-retrieval-answer-baseline` (Tasks 0–11, HEAD `07a79b7`, 222 tests, offline eval PASS).
  A pre-flight scan fixed 7 plan conflicts and 3 weak tests before coding. Deviations, all recorded
  as rulings in the local SDD ledger: crash- and interrupt-safe spend accounting in `live.py`,
  budget base always includes `experiments/issue-8`, non-finite/negative provider cost books the
  reservation, the decision model sends OpenRouter's documented `reasoning: {"effort": "low"}`,
  the report adds a per-call table and labels deterministic safety apart from prompt injection.
  The whole-branch review before the paid run found two critical gaps (a rejected request would
  book ≈ $0.25 without diagnosis; a provider error on the injection case gave REVERT); fixed with
  a pre-spend capability check, stop on 4xx or two consecutive errors, stored error text, and
  "not measured" → INVESTIGATE for injection provider errors. Nothing pushed, no money spent.
  Open for the owner: injection contract violation REVERT vs INVESTIGATE, and the Task 12 go.
- 2026-09-14: Owner ruled a contract violation on the prompt-injection case stays REVERT, then
  approved the paid run. Pre-run checks on `6e44205` passed (222 tests, ruff, smoke, corpus,
  offline eval 7/7; `/models` prices unchanged, all sent parameters supported). The key was not
  available to the agent; Petr ran `make eval` in his own terminal. Live run `20260914T145319Z`:
  complete, 18 calls, $0.024 (provider-reported), no key material in the artifact. Owner delegated
  the manual verdicts to the agent and ruled the doubtful military-leave case himself; the report
  states this. Verdict **INVESTIGATE**: groundedness 6/7 (gpt-5-mini named two Texas leave types
  whose table rows do not list TX), task success 5/7 (also answered the missing-data military
  case before clarifying), abstention 1/1, prompt injection PASS, deterministic safety 6/6.
  DeepSeek abstained on Texas and invents nothing there, but is not reviewed. Owner chose to
  record both failures as known v0.1 limitations and move on to Issue #9 — a minimal working
  system first; prompt fixes and a rerun go to Issue #13 with retry/repair. Limitations: one run,
  repeat 1, Recall@1 non-discriminating (decision 0003), mostly agent-made review verdicts.
- 2026-09-14: Independent QA of PR #22 in a fresh context returned PASS for `8eb2ca2` (all checks
  rerun, tests pass without network, dataset and prompt hashes match the run). Owner accepted;
  squash-merged as `2652d3e`, `main` verified locally and in CI, Issue #8 closed. Issue #9 groomed
  to Ready with owner decisions: pure policy functions called by #10/#11 (D1), in-memory
  `LeaveRequest` defined in #9 and persisted by #10 (D2), out-of-scope request access returns
  `not_found` and `forbidden` is reserved for commands a role never has (D3).
- 2026-09-21: Implemented Issue #9 (authorization and role-specific projections) with TDD on
  `feat/9-authorization-role-projections`: new `leave/access_policy.py` (`resolve_identity`,
  `can_view`, `visible_requests`, `authorize_command`, `authorize_replay`,
  `authorize_audit_history`, `project_for`), a new immutable `LeaveRequest` entity and
  `WorkflowError` in `leave/contracts.py`, and `retrieval.retrieve_for_identity` as the new
  authorized retrieval entry point. Rewired the offline eval's `role_view`, `forbidden_disclosure`,
  and `forbidden_document` safety cases to exercise the real policy instead of hand-built
  projections. First independent review (code-reviewer agent) found two blockers: (1) every
  policy function trusted any hand-built `DemoIdentity` without checking it against the manifest
  — a forged identity got another employee's HR projection and could run an HR command; (2)
  `answer_question` still called `retrieve()` by bare role, so `retrieve_for_identity` was only
  exercised in the eval scorer, not on the production path (AC-4 not actually met). Fixed both:
  `_verify_bound()` now gates every policy entry point, and `answer_question`'s public parameter
  changed from `role: ActorRole` to `identity: DemoIdentity` (all callers updated). Also
  strengthened `_score_role_view` (exact `ROLE_PROJECTION_FIELDS` key set per role) and
  `_score_forbidden_disclosure` (asserts a real secret string is absent from serialized JSON,
  not just `hasattr`). Second independent review: APPROVE, both blockers verified closed, no new
  blocker. PR #24 squash-merged to `main` (980b2c6), Issue #9 closed; 256/256 tests, ruff/format
  clean, offline eval 8/8 knowledge + 7/7 safety. Non-blocking follow-ups filed as Issue #25:
  verify identity at the retrieval boundary once #10/#12 add a real entry point, derive
  `EVAL_IDENTITY`/`EVAL_ROLE` from the manifest instead of duplicating it, and a
  `LeaveRequest.employee_id` role invariant. Next: Issue #10 (persistence) / #11 (confirmation,
  idempotency), calling `access_policy` rather than re-deriving access (D1/D2).
- 2026-09-21: Groomed Issue #10 from Draft to Ready after reconciling completed dependencies #6
  and #9, then implemented it with TDD on `feat/10-leave-sqlite-storage`. Added the deterministic
  v0.1 state machine and an authorized SQLite repository with optimistic version checks,
  reproducible schema initialization, restart persistence, atomic request+audit transactions,
  ordered audit reconstruction, and database triggers that prevent audit update/delete. Audit
  rows contain only transition metadata; payload comments, clarification text, provider output,
  and hidden reasoning are excluded. Integration tests cover every lifecycle mutation, all
  undeclared status/command pairs, stale versions, cross-employee denial, restart persistence,
  migration re-entry, forced audit failure rollback, audit ordering, and append-only enforcement.
  Confirmation validation and idempotent replay remain out of scope for #10 and are reserved for
  #11. An adversarial self-review (separate reviewer unavailable in this session) hardened the
  migration runner against partial/falsely versioned schemas and marked two internal-only
  boundaries: full-record reads require later projection, and submit must not be exposed before
  #11 validates confirmation and idempotency. Local evidence: 279 tests pass, smoke 2/2, Ruff and
  format checks clean. Pending independent QA, owner acceptance, PR, and merge.
- 2026-09-21: Independent QA reviewed PR #26 (Issue #10) with adversarial probes rather than
  reading tests only: killed the process between the request UPDATE and the audit INSERT (no
  orphan row on either side), raced two processes on the same optimistic-version write (loser
  got `VERSION_CONFLICT`, no lost update), confirmed the append-only triggers and reproducible
  restart persistence. Verdict PASS. Filed five non-blocking findings as acceptance criteria
  instead of patching in-branch: `CONFIRM_SUBMIT` does not validate `payload_digest` against the
  stored payload (→ Issue #11; a blanket reject-all guard was tried and reverted — it broke
  `test_update_and_every_declared_transition_are_persisted`, which already exercises
  `CONFIRM_SUBMIT` as a working transition, so the real fix is digest validation via
  `WorkflowErrorCode.STALE_CONFIRMATION`); `get()`/`execute()` return un-authorized/un-projected
  full records (→ Issue #14, apply `project_for` before any HTTP response); raw `sqlite3`
  exceptions and unclosed connections are unsafe under a live server (→ Issue #14, before FastAPI
  is wired up). PR #26 squash-merged to `main` (`97a29ab`), Issue #10 closed, `main` re-verified
  (279/279 tests).
- 2026-09-21: Groomed Issue #11 with the carried D1/D3 authorization decisions and the blocking
  digest-validation finding from #10, then implemented it on
  `feat/11-confirmation-idempotency` (`448f388`). Added a normalized confirmable preview,
  stored-payload digest validation (`STALE_CONFIRMATION`), SQLite schema v2 idempotency records
  scoped by actor+operation+key, authorized replay of the original result, conflict rejection,
  and atomic request+audit+result commits. Integration coverage includes tampered confirmation,
  replay/conflict, actor/operation scoping, ownership change, rollback after result-write failure,
  and a concurrent double-submit with one transition/event. The offline stale/duplicate eval
  cases now exercise the real SQLite command path instead of contract/fingerprint stand-ins.
  Первый независимый QA PR #27 нашёл блокер: после persisted edit старая envelope безопасно
  отклонялась, но возвращала `VERSION_CONFLICT` вместо требуемого `STALE_CONFIRMATION`; eval
  проверял только tampered digest без реального edit. Добавлены regression integration/eval
  сценарии и исправлен порядок проверок (`149e17e`). Повторный QA PASS, hosted CI зелёный, owner
  acceptance получен. PR #27 squash-merged в `main` как `37ff0b1`; Issue #11 закрыт с `done`,
  локальный и hosted `main` проверены (289 тестов, smoke 2/2). Следующий путь до показа:
  #12 offline vertical slice → #13 knowledge/workflow integration → #14 role-aware demo UI.
- 2026-09-22: Groomed Issue #12 `draft → ready` (dependencies #9/#10/#11 all merged), planned via
  an Explore agent (mapped existing layers: no application-service module exists; the
  `evals/run.py` pattern of `bind_server_command`+`repository.execute` is the real precedent for
  "public application boundaries") and a Plan agent, then implemented `tests/smoke/` on
  `feat/12-offline-fake-adapter-smoke`: a single positive end-to-end journey (knowledge-slice
  answer via `ScriptedProvider` → draft → preview/confirm → HR clarification → re-confirm → HR
  processing → employee/manager/HR projections) and four negative variants (forbidden access,
  stale confirmation, duplicate submission, fake-provider failure). No `src/` change was needed —
  `state_machine` and `access_policy` already covered every transition/projection. Independent
  QA (code-reviewer agent) found two real gaps: the fake-provider-failure test asserted no
  exception leaked but never proved leave-workflow state was untouched, and the
  "employee attempts HR command" negative case exercised `access_policy.authorize_command`
  directly while the real composed path (`bind_server_command`) actually rejects the same input
  earlier with a bare `ValueError`, not the typed `WorkflowError(FORBIDDEN)` the test implied was
  reachable. Both fixed: the provider-failure test now snapshots repository state before/after;
  the forbidden-access test now asserts the real `ValueError` behavior explicitly alongside the
  boundary-level `authorize_command` check. The `ValueError`-vs-`WorkflowError` inconsistency
  itself was filed as non-blocking Issue #28 (`bind_server_command`'s role/command guard should
  raise a typed error for a clean future HTTP mapping in #14). PR #29 squash-merged to `main`
  (`e70ed9c`), CI green, Issue #12 closed; `main` re-verified (301/301 tests, 7/7 offline smoke
  via `make eval-smoke`). Next: #13 knowledge/workflow integration → #14 role-aware demo UI,
  with #28 to resolve before or alongside #14.
- 2026-09-22 (second session): Groomed Issue #13 `draft → ready` (dependencies #8/#12 both
  closed; the issue's own "Ready/open decisions" field already declared no unresolved decisions
  once they land). Planned via the same Explore-then-Plan agent pattern: Explore mapped the
  `knowledge/answer.py::answer_question` retrieval/answer path and the `leave/` typed-workflow
  boundaries (`bind_server_command`/`repository.execute`/`access_policy.project_for`) and
  confirmed the two packages have zero cross-imports today — the knowledge→workflow bridge does
  not exist anywhere. Plan agent designed a 12-step TDD plan, saved to
  `docs/superpowers/plans/2026-09-22-issue-13-integrate-grounded-answers.md`. Key design
  decisions: (1) fix Issue #28 first as a prerequisite, not a follow-up, since orchestration
  multiplies `bind_server_command` call sites and AC-3's "state unchanged on invalid input"
  needs a typed error to test against; (2) structured leave-field extraction gets its own new
  contract (`LeaveFieldProposal`) and prompt (`leave-fields-v1`) rather than extending the
  existing `AnswerContract`/`answer-v1`, to avoid invalidating the recorded Issue #8 baseline and
  because citation-backed answers and employee-stated dates are different validation regimes;
  (3) new modules land inside `leave/` (`assistant.py`, `field_proposal.py`) per the framework's
  package boundary, not a new top-level package. No code was written — planning only. Next:
  implement the plan (a fresh session was recommended to start it, this one having grown to
  ~106K tokens of planning context).
- 2026-09-22 (third/fourth/fifth sessions): Implementing the Issue #13 plan via
  subagent-driven-development in worktree `.claude/worktrees/issue-13-integrate-grounded-answers`
  (branch `worktree-issue-13-integrate-grounded-answers`), one fresh implementer + one fresh
  reviewer subagent per step, ledger at
  `.superpowers/sdd/2026-09-22-issue-13-integrate-grounded-answers/progress.md`. Step 1 (fix
  Issue #28 — typed `WorkflowError(FORBIDDEN/UNAUTHORIZED)` from `bind_server_command`, commit
  `966c310`) and Step 2 (`tests/integration/conftest.py` scaffolding, commit `de8d9c2`) landed
  clean. Step 3 (`leave/assistant.py`: `AssistantOutcomeKind`, `GroundedAnswer`,
  `AssistantOutcome`, `answer_for_actor` — deterministic mapping from the knowledge pipeline's
  `OutcomeKind`/`AnswerStatus` onto typed outcomes, with an exhaustive `match` and no
  eligibility/jurisdiction logic per the plan's D-D) landed clean, commit `0521823`, 307/307
  tests, review Approved with only two deferred-minor findings (dead assertions in
  `tests/unit/test_leave_assistant.py`, real invariants covered elsewhere). The `task-brief`
  script remains incompatible with the plan's `### Step N` headers, so each step's brief is
  still assembled by hand from the plan file — third step running on this workaround without
  issue. Branch stays unpushed to `origin` until all 12 steps and the final whole-branch review
  land (single PR for the whole plan). Step 4 (`create_draft_from_fields`/
  `provide_clarification_from_fields`, AC-1 write path, commit `a70f774`) landed after one fix
  round: initial review approved the production code (server-supplied invariant honored — no
  internal `uuid4()`/`datetime.now()`, no branching on payload/question/model output — D-C/D-D
  honored, existing interfaces used correctly) but flagged one Important plan-mandated gap: the
  new integration test read stored state for its digest comparison via `repository.get(...)`
  directly instead of via `access_policy.project_for`, contradicting the brief's explicit
  interface note. Fix (commit `7567e58`) rebuilt the payload from an `EmployeeLeaveProjection`
  instead; re-review confirmed addressed, no new breakage. 309/309 tests. Step 5 (`build_clarification_request` in `leave/assistant.py`, commit `f34f0ed`)
  landed clean on the first review: an explicit guard chain (kind is `UNAVAILABLE`/`ABSTAINED` →
  empty citations → blank/missing `clarifying_question` → length) rejects Step 3's two
  `ABSTAINED` sources (`NO_EVIDENCE` and `ANSWER`+`AnswerStatus.ABSTAINED`) uniformly with a
  single check, resolving the Step 3 design note as-is with no special-casing needed; the
  question text is the model's `clarifying_question` plus a code-built `" (source: <ids>)"`
  suffix built only from `GroundedAnswer.citations` (never retrieved document text), truncated
  to fit `RequestClarificationInput`'s `max_length=500` with a `ValidationError` backstop so
  nothing untyped escapes; no role/actor check inside the function (D-D) — an integration test
  proves an employee actor gets a typed `WorkflowError(FORBIDDEN)` via the real
  `bind_server_command` path with byte-identical stored state. 317/317 tests, review Approved,
  0 Critical/Important findings. Step 6 (`leave/field_proposal.py`: `LeaveFieldProposal`
  contract + `parse_field_proposal()`, plus `prompts/leave-fields-v1/{system.md,user.md}`, per
  D-B, commit `7673169`) landed clean on the first review: `missing_fields()` is computed by
  code from which of the three required fields are `None`, never read from model output;
  `to_payload()` builds a `LeaveRequestPayload` only when complete, raising
  `WorkflowError(VALIDATION_FAILED)` otherwise, with a `ValidationError` backstop so nothing
  untyped escapes; `parse_field_proposal()` mirrors `parse_answer()`'s JSON→pydantic→typed-error
  shape but with only two failure stages (no citation check — field proposals carry none); the
  extraction prompt templates only `{detail_text}`, never retrieved document text.
  328/328 tests, review Approved, 0 Critical/Important, two deferred minors (an unused
  schema-name constant provisioned for Step 7; a defence-in-depth branch under-commented at its
  own site). Next: Step 7 (`propose_leave_fields` orchestration + proposal→command bridge),
  which also carries the `ScriptedProvider(key=...)` addition deferred from D-E's Step 3 ruling.
  Step 7 (commit `f06c362`) added `propose_leave_fields`, `build_create_draft_input` and
  `create_draft_from_proposal` (delegating to Step 4's `create_draft_from_fields`, no second
  write path) plus the backward-compatible `ScriptedProvider(key=...)`; 341/341 tests, review
  Approved first time. Step 8 (commits `c37d880`, `4e28551`) is a test-only module,
  `tests/integration/test_assistant_failure_paths.py`, covering all eleven failure-path rows
  (invalid JSON, schema, citation not retrieved, timeout, 503, prompt injection with a refusing
  and an obedient model, role spoofing, forbidden document before context, forbidden content in
  records, non-US question); each seeds a real draft and asserts it unchanged. Role spoofing
  surfaces as `WorkflowError(FORBIDDEN)` in both directions. One review round: the
  citation-not-retrieved row now pins that a model-fabricated document id appears only in
  `AssistantFailure.detail` (diagnostic, from `ContractViolation.detail`), never in answer,
  guidance or citations — a known limitation for Issue #14: the UI must not render that field.
  353/353 tests. Next: Step 9 (wire `expects_clarification` into the eval scorer). Step 9 (commit `92cbf85`) scores `expects_clarification`:
  `KnowledgeCaseResult.clarification_ok`, a separate reported-only `clarification` count in
  `evals/decision.py` (recall tally kept numerically identical, no gate change). Re-scoring the
  stored #8 run gives clarification 1/1 for gpt-5-mini and 0/1 for deepseek-v3.2 — the documented
  "answered before clarifying" failure, now an explicit number. The decision CLI refuses to
  re-score that run on this branch (pre-existing `source_changed_since()` staleness gate), so the
  figure came from `compute_model_metrics()` directly. Review Approved first time. Next: Step 10.
