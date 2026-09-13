# Retrieval and answer baseline — design

Status: draft 2026-09-13 (revised after independent Codex review; see
`2026-09-13-retrieval-answer-baseline-codex-review.md`)
Related: Issue #8, `docs/decisions/0001-v0.1-evidence-granularity.md`,
`docs/decisions/0002-v0.1-baseline-defers-chunking.md`,
`docs/superpowers/specs/2026-09-13-micro-eval-dataset-design.md`, `evals/cases/v0.1.yaml`

## Goal

Produce the first reproducible, evidence-grounded answer baseline for the knowledge-answer
categories (`normal`, `missing_data`, `unsupported_eligibility`, `out_of_scope`) that Issue #7
left stubbed, plus real scoring for `prompt_injection`, the one safety category whose outcome
depends on what a live model actually does with untrusted input. Replace `_stub_knowledge_answer`
and the two placeholder scorers with real logic, run once against a live provider under an
approved budget, and publish a KEEP/REVERT/INVESTIGATE decision.

`provider_failure` is scored offline against a fake adapter that injects a timeout/error (see
Testing) — a real live call can't be made to fail to order, so it is not part of the live run.

## Scope

In scope: a lexical retrieval baseline, a provider-neutral LLM adapter over OpenRouter, an
httpx-based HTTP client, a validated answer contract (citations, abstention), a budget-guarded
live eval run, recorded fixtures for offline tests, and the baseline report/decision.

Out of scope: vector search, sub-document chunking (decisions 0001 and 0002 — evidence stays
whole-document; 0002 explicitly amends Issue #8's original chunking line, it is not an inference
from 0001 alone), an agent planner, workflow mutations, scoring `expects_clarification` (stays
metadata-only, tracked as a known limitation), provider lock-in.

## Retrieval

A trivial lexical keyword-overlap ranker, operating over every document currently in the corpus
(not hardcoded to a count):

- Tokenize the question and each document's text into a lowercased word set.
- Score each document by the size of the intersection with the question's word set.
- Return the single highest-scoring document (`k = 1`, fixed — not a per-case parameter; no
  eval case in `v0.1.yaml` expects more than one document as evidence).
- If every document scores 0 (no shared words), retrieval returns an empty result. The answer
  step must then abstain rather than fall back to an arbitrary document — grounding a wrong
  citation on a zero-overlap document would violate groundedness more directly than an honest
  abstention.
- Document-level authorization filtering runs before ranking; a forbidden document is never
  scored or returned regardless of overlap. This is new work for Issue #8, not inherited from
  Issue #6 — Issue #6's permission manifest governs workflow-request visibility (who can see
  whose leave request), it has no document-access dimension and defines no forbidden-document
  fixture. Concretely:
  - `data/manifest.json` documents gain an `access` field (`"public"` for both current
    documents).
  - A synthetic restricted document is added at
    `data/source/people-policies/_synthetic_restricted/hr-only-note.md`, fully authored for this
    test (not derived from the real GitLab handbook snapshot, so it carries no provenance/licence
    fields in `manifest.json` beyond `access: "hr_only"` and its own sha256) — it exists only to
    give the forbidden-fixture acceptance criterion something concrete to check.
  - One new eval case (`forbidden-document-retrieval`, category `out_of_scope` or a new
    `forbidden_document` safety category — implementation plan picks the schema shape) asserts
    this document is never retrieved for the default `employee` role even when its content
    keyword-overlaps the question. This is a retrieval-layer check, scored offline against the
    fake adapter like the other safety cases — it does not need a live model call.
  - The retrieval step receives the caller's role/access level as an input and drops any
    document whose `access` the caller doesn't satisfy before scoring, not after.
  - This brings the case set to 15 (the 14 in `evals/cases/v0.1.yaml` plus this one). All "14
    cases" language below becomes 15 once this case is added; it does not exist yet as of this
    spec revision — adding it is part of the Issue #8 implementation, not a prerequisite for
    approving the design.

This is deliberately simple, not a placeholder: with the current two-document, topically
asymmetric corpus (`_index.md` company-wide overview vs. `us.md` detailed US policy — every
`v0.1.yaml` case's `expected_evidence` cites `us.md` only), overlap scoring has a real,
measurable signal to discriminate on, so Recall@k is not trivially 100%.

## Provider-neutral adapter

- HTTP client: `httpx`, added as a new dependency. Chosen over the `openai` SDK so the adapter's
  shape does not carry an OpenAI-specific contract, matching the "provider-neutral adapter"
  scope language.
- Provider: OpenRouter. Live baseline model: GPT-5 mini (primary). Second model for comparison:
  DeepSeek V3.2. Both selected per-run, not frozen into code — the adapter takes model id and
  parameters as configuration.
- Issue #8 asks for "one configured live baseline"; running two models is a deliberate addition
  for comparison data, not two baselines. **GPT-5 mini is the configured baseline that the
  KEEP/REVERT/INVESTIGATE decision is made on.** DeepSeek V3.2's results are reported alongside
  it (same report, same metrics) but are informational only — they do not change the decision.
  If GPT-5 mini fails outright (e.g. unavailable) DeepSeek V3.2 does not implicitly become the
  baseline; that requires a new explicit run.
- The adapter returns a validated answer contract: cited fragment IDs (document IDs, per
  decision 0001), the answer text, and an explicit abstain flag. `abstain` means "no retrieved
  evidence supports any answer" — it is not the same as asking a clarifying question. A response
  can carry a citation, an answer, and a clarifying question together (this is exactly what
  `missing-data-military-leave` expects: partial USERRA answer, cited, plus a question about
  branch/duty type); only the true no-evidence case sets `abstain`.
- Model id, parameters, and prompt hash are recorded with every run, per Issue #8's scope
  constraint.

## Budget guard

- Hard ceiling: **$0.50** per eval run. Of the 15 cases, only the 9 knowledge (`normal`,
  `missing_data`, `unsupported_eligibility`, `out_of_scope`) and `prompt_injection` cases call a
  live model; the other 6 safety/retrieval cases are scored offline against a fake adapter (see
  Testing). Expected cost for those 9 cases × 2 models ≈$0.03 (≈16x headroom for retries/reruns
  within a session).
- Two-part guard, since cost is only known after a call completes and a post-response-only check
  can't stop the call that pushes the run over:
  - **Pre-call reservation**: before each call, the runner estimates worst-case cost from
    `max_tokens` and the model's published per-token price, and refuses to start the call if
    cumulative reserved cost would exceed $0.50.
  - **Post-response reconciliation**: actual cost from the response replaces the reservation;
    the runner aborts further calls (but keeps results already recorded) if reconciled cumulative
    cost exceeds $0.50 despite the reservation (e.g. price data was stale).
- This is a runner-level guard, not a per-case limit; Issue #8 does not need finer granularity
  given the case count and expected per-case cost are both small and stable.
- A run that aborts partway still writes whatever cases completed to the fixture/report as a
  partial result, clearly marked incomplete — it is not treated as a valid full baseline.

## Offline fixtures

- During the one approved live run, every raw provider response for the 9 model-calling cases
  (see Budget guard) across both models is recorded into a single file, `evals/fixtures/v0.1-live.json` (list of records: case id,
  provider, model, request, raw response, usage/cost).
- This file is committed to git. The repository is private and the only case with a synthetic
  name (`prompt_injection`'s "Jane Doe") is fictional. The adapter's recorded `request` field is
  limited to what the eval actually needs to reproduce: the case's question/scenario text, the
  retrieved document ID(s), model id, and generation parameters — never the OpenRouter API key,
  auth headers, or other transport-level fields, which the adapter strips before the record is
  built. This scoping, not just the repo being private, is what makes committing the fixture
  safe.
- Offline tests and CI use a fake adapter that reads from this file instead of calling the
  network. No test in CI makes a paid call, per Issue #8's acceptance criteria.
- If the corpus, prompts, or model selection change later, the fixture file is regenerated by a
  new approved live run — it is not hand-edited.
- Each record in the fixture stamps the prompt hash, corpus revision (from `manifest.json`),
  model id, generation parameters, and the eval schema version it was generated against. Offline
  tests check all five against current values before trusting a record — a stale fixture (any
  one of these changed since the live run) fails loudly instead of silently passing CI against
  an outdated response.

## `expects_clarification` (deferred)

The `missing-data-military-leave` case is the only one of 14 marked `expects_clarification:
true`. Issue #8's acceptance criteria do not mention detecting clarification behavior, and
reliably distinguishing "the agent asked a clarifying question" from "the agent answered and
also asked something" is a non-trivial scoring problem in its own right. This stays unscored in
v0.1 (already tracked as a known limitation from Issue #7); revisit only if a future issue
introduces a real multi-turn clarification workflow.

## Testing

- Retrieval: overlap scoring on fixtures with clear-winner, tie, and zero-overlap inputs; k=1
  output shape; authorization filtering still excludes forbidden documents regardless of score.
- Adapter: request/response shape against a fake transport (no network); answer contract
  validation rejects a response with no citation and no abstain flag.
- Runner: budget guard aborts a simulated run that would exceed $0.50; fixture-backed fake
  adapter drives `provider_failure` (timeout/error) and `prompt_injection` scoring without any
  paid call.
- Live: one approved run against OpenRouter (GPT-5 mini + DeepSeek V3.2), the 9 model-calling
  cases, recording `evals/fixtures/v0.1-live.json` and producing the baseline report. The
  remaining 6 cases (forbidden disclosure, stale confirmation, duplicate submission, provider
  failure, role-view consistency, forbidden-document retrieval) are exercised offline only, as
  part of the same test suite, not the live run.

## Open questions for the implementation plan

Raised by the Codex review, not blocking the design decisions above but not yet resolved — the
implementation plan must settle these explicitly rather than let the code decide them ad hoc:

- Exact tokenization for keyword overlap (regex/Unicode/stopwords/stemming) and the tie-break
  rule when two documents score equal (the review found a real tie case: naive `\w+` tokenization
  gives `_index.md` and `us.md` equal overlap on the Germany out-of-scope question).
- What "supporting citation" requires beyond a valid document ID: must the cited ID be in the
  retrieved set, and how (if at all) is claim-to-content support checked.
- How groundedness and task success are actually scored — the current scorer handles evidence-ID
  overlap and abstention, not free-text `expected` comparison.
- The exact answer-contract shape (one enum vs. multiple flags; behavior for an
  unknown/forbidden/non-retrieved citation). Whether answer+citation+abstain can co-occur is
  resolved above (abstain is reserved for the no-evidence case, distinct from a clarifying
  question).
- Exact model IDs, prompt version, generation parameters, timeout, and retry policy, fixed before
  the live run.

## Baseline report and decision

Per Issue #8's acceptance criteria: report Recall@1, groundedness, abstention, task success,
latency, tokens, cost, counts and percentages, and raw failures for both models — GPT-5 mini as
the decision-bearing configured baseline, DeepSeek V3.2 alongside it for comparison only (see
Provider-neutral adapter). End with KEEP/REVERT/INVESTIGATE on GPT-5 mini and a concrete next
action; any threshold change after seeing results must carry a written reason, not a silent
adjustment.
