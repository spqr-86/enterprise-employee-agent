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
