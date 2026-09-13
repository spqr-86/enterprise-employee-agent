# Adversarial review — retrieval and answer baseline (spec revision 2)

Reviewed artifact: `2026-09-13-retrieval-answer-baseline-design.md` at commit `873a3d9`
Reviewer: Claude `code-reviewer` subagent, adversarial mode
Review date: 2026-09-13
Verdict: REQUEST CHANGES

Findings were re-checked against the code before revision 3; overlap numbers reproduced exactly.

## Critical

1. **Recall@1 is trivially 100%.** Naive `\w+` overlap: `us.md` wins all 7 cases with
   `expected_evidence` (12:6, 18:8, 7:4, 7:4, 5:2, 9:3, 10:7); Germany ties 9:9 but is an abstain
   case where the scorer ignores evidence. A constant "always `us.md`" ranker also gets 7/7. The
   spec claimed the opposite as the justification for k=1.
2. **Abstain contract contradicts itself.** Zero overlap never occurs (minimum is 2), so the
   retrieval-driven abstain branch is unreachable; the only abstain case receives a relevant
   document with overlap 9, so abstain must come from model judgement, which was not specified.
   `out-of-scope-texas-detail` expects a partial refusal but `abstain_expected: false`.
3. **Restricted document breaks corpus validation and a project boundary.** A manifest entry
   without provenance fields raises `CorpusError` (`_REQUIRED_DOCUMENT_FIELDS`), and
   `load_manifest()` is the first call in `evals/run.py:main()`. `data/source/` is a byte-stable
   handbook subset changed only by a data-scope decision; `data/synthetic_protected/` already
   exists for synthetic fixtures.
4. **Blocking points of the first review were dropped, not resolved:** no text → `refused` /
   `error_surfaced` mapping (while prompt injection is the stated reason for a live call), and no
   KEEP/REVERT/INVESTIGATE rule tied to the 90%/100% thresholds required by Definition of Ready.
5. **"9 / 6" topology is inconsistent.** There are 8 knowledge cases, not 9; leaving the new case's
   schema open (`out_of_scope` vs new safety category) changes live-call count and budget.

## Remarks

- Forbidden-document test can pass vacuously if the fixture never outranks `us.md` without the
  filter.
- Issue #8's "abstain/escalate": escalate missing from the contract.
- Issue #8's manual review of failures and a sample of passes not carried into the report.
- Fixture staleness + no hand edits = every prompt change needs a new paid run to unbreak CI.
- `corpus_version` is manually maintained; corpus changes without a mandated bump defeat the
  staleness check.
- $0.50 per run with "headroom for reruns" has no cumulative limit; price source and missing
  `cost` undefined.
- Two models in one fixture, but the fake adapter has no model ID input.
- `provider_failure` described both as fake-injected error and as fixture-backed, while the fixture
  holds only successful calls.

## Nits

- Residual "one of 14" wording; "corpus revision" vs actual field `corpus_version`.

## Done well

- Separation of abstain from clarifying question.
- Scoped `request` contents with auth headers stripped.
- Decision 0002 framed as an explicit scope amendment.
