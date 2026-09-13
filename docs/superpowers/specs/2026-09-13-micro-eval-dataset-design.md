# Micro-eval dataset: schema, validator, scorer — design

Status: approved 2026-09-13
Related: Issue #7, `docs/decisions/0001-v0.1-evidence-granularity.md`,
`evals/cases/draft-v0.1-micro-eval.md`

## Goal

Turn the 14 reviewed draft cases into a versioned, machine-checkable dataset with a deterministic
validator and scorer, per Issue #7's acceptance criteria. No model calls, no retrieval — v0.1
evidence is whole-document IDs (decision 0001).

## Scope

In scope: case schema, dataset file, validator, scorer, report format, unit tests, a held-out
partition *policy* (not applied yet — dataset stays 14 open cases; applies when the dataset grows
to ~30-40 per PLAN.md).

Out of scope: model/retrieval baseline (Issue #8), sub-document chunking, live evaluation runs.

## Components

- `src/enterprise_employee_agent/evals/schema.py` — pydantic models for a case, following the
  `ContractModel` (strict, frozen) convention already used in `leave/contracts.py`.
- `src/enterprise_employee_agent/evals/validator.py` — dataset-level checks, run before scoring.
- `src/enterprise_employee_agent/evals/scorer.py` — per-case scoring + result aggregation.
- `src/enterprise_employee_agent/evals/reporting.py` — formats an aggregate into a text report
  (counts + percentages per category, plus a separate deterministic-safety section).
- `evals/cases/v0.1.yaml` — the 14 cases in the new schema. The existing
  `evals/cases/draft-v0.1-micro-eval.md` is kept as the human-review record, not deleted.
- `evals/run.py` (invoked as `python -m enterprise_employee_agent.evals.run`) — loads the
  dataset, validates it, scores every case (workflow-category cases against the already-built
  Issue #6 code directly; knowledge-category cases against a fixture/stub answer in v0.1, since
  there is no model integration yet), prints the report.

## Case schema

Common fields on every case:
- `id`: unique string
- `category`: enum — `normal`, `missing_data`, `unsupported_eligibility`, `out_of_scope`,
  `prompt_injection`, `forbidden_disclosure`, `stale_confirmation`, `duplicate_submission`,
  `provider_failure`, `role_view`
- `question` or `scenario`: free text (question-shaped cases vs. scenario-shaped cases)
- `expected`: free-text description for human review — not machine-compared verbatim
- `held_out`: bool, default `false` — reserved for the future held-out partition (see below);
  no case is `true` yet

Knowledge categories only (`normal`, `missing_data`, `unsupported_eligibility`, `out_of_scope`):
- `expected_evidence`: list of document IDs from `data/manifest.json`, OR empty with
  `abstain_expected: true` — never both empty and `abstain_expected: false`
- `expects_clarification`: bool

Safety/workflow categories only (`prompt_injection`, `forbidden_disclosure`,
`stale_confirmation`, `duplicate_submission`, `provider_failure`, `role_view`):
- `expected_outcome`: a short machine outcome code the Issue #6 code actually returns (e.g.
  `refused`, `rejected_stale`, `idempotent_replay`, `error_surfaced`) — compared by code, not by
  matching prose.

The schema is a pydantic discriminated union on `category`, matching the variant-by-type pattern
already used for request types in `leave/contracts.py`.

## Validator (dataset-level, runs before scoring)

- All `id` values unique.
- Every ID in `expected_evidence` exists in `data/manifest.json`'s `documents[].id`.
- Knowledge case: `expected_evidence` non-empty XOR `abstain_expected: true` (not both empty and
  false).
- Safety/workflow case: `expected_outcome` present.
- A validation failure is a hard error listing every problem found; scoring does not start
  against an invalid dataset.

## Scorer

- Knowledge cases: `recall = |actual_evidence ∩ expected_evidence| / |expected_evidence|`;
  groundedness in v0.1 reduces to the same check (evidence is whole-document, per decision 0001);
  abstention cases (`abstain_expected: true`) are scored separately as correct-abstain vs.
  fabricated-answer, not folded into recall.
- Safety/workflow cases: `actual_outcome == expected_outcome`, pass/fail only, never expressed as
  a percentage.
- Zero cases in a category → report shows `n/a (0 cases)`, never `0%` and never a hard error.

## Report

- Per knowledge category: count, pass count, percentage.
- A separate "deterministic safety" section: explicit list of failing case IDs. Any failure in
  this section marks the whole section FAIL in the report — it is never averaged into an overall
  percentage (per Issue #7: "deterministic safety failures cannot be averaged away").

## Testing (TDD — written before the implementation)

- Schema: valid case per category parses; invalid combinations (missing required field for the
  category, both `expected_evidence` empty and `abstain_expected: false`) are rejected.
- Validator: duplicate IDs, an evidence ID absent from the manifest, zero cases in a category.
- Scorer: recall on a fixture with partial/complete/no evidence overlap, correct vs. fabricated
  abstention, safety pass/fail, and that a safety failure flags its section without touching the
  knowledge percentages.

## Held-out partition policy (defined, not applied yet)

Dataset stays fully open at 14 cases (all are used for tuning/reference now — no case is hidden).
When the dataset grows toward the 30-40 range (per `PLAN.md` next step), a fixed subset will be
marked `held_out: true` in the schema and excluded from any prompt/threshold tuning; its expected
values must not be inspected during tuning work. This flag field exists in the schema now
(defaulting to `false`) so adding held-out cases later does not require a schema migration.
