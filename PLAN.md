# Enterprise Employee Agent — plan

## 0. Constitution

- The v1 corpus is a frozen, public GitLab Handbook HR subset; source changes require a deliberate data-scope decision.
- The product scope is one end-to-end leave-of-absence workflow, not a universal enterprise automation platform.
- The workflow uses local educational state and must never present itself as Tilt, Okta, or GitLab production infrastructure.
- Access decisions are enforced before retrieval and again before rendering role-specific results.
- An action is prepared, previewed, explicitly confirmed, and idempotent before it changes local state.
- New workflow transitions begin with tests; model-dependent outcomes are evaluated by outcome category rather than exact prose.
- No secrets enter version control; no remote push or external write occurs without an explicit instruction.

## 1. Goal

Build a demonstrable corporate assistant that grounds HR answers in GitLab Handbook documents and completes a bounded leave-of-absence workflow. An employee can ask what applies, provide missing details, review a request, submit it to a local learning service, and see its status. A manager can act on the request but sees only the minimum operational information; HR sees the sensitive details needed to process it.

## 2. Data and inputs

The planned source is the existing frozen 47-file GitLab Handbook HR subset, documented in `data/README.md`. The first slice is the company-wide and US leave-of-absence material. A local fixture set supplies identities, roles, request state, and a clearly labelled demonstration permission manifest.

## 3. Architecture

The candidate architecture is a typed workflow, not a free-running planner:

`user request -> allowed-document retrieval -> fact extraction -> clarification or preview -> explicit confirmation -> idempotent local request write -> role-specific status view`

Components will live in `agents/`, `tools/`, `llm/`, `prompts/`, `schemas/`, `evals/`, and `tests/`. Retrieval, policy interpretation, state transition, and rendering remain separately testable.

## 4. Why this is useful

Most document chat demos stop at an answer. This one makes the boundary visible: the employee gets only allowed handbook evidence, a sensitive request is represented differently for employee, manager, and HR, and the agent performs one safe, auditable action only after confirmation.

## 5. Verification and evaluation

- Unit tests for visibility projections, workflow transitions, validation, and idempotency.
- Smoke test covering question -> clarification -> preview -> confirmation -> submitted request -> manager decision -> employee status.
- Evaluation cases for unknown jurisdiction, unsupported eligibility facts, forbidden disclosure, duplicate submission, and a role change on the same request.
- Every generated answer must cite an allowed handbook fragment or state that the source cannot establish the answer.

## 6. Current status

- Project foundation created on 2026-09-12.
- Existing GitLab corpus located and assessed; no data copied yet.
- Draft product spec written; architecture choice is pending.
- No application code or external integration exists.

## 7. Next steps

1. Choose an approach in `docs/spec-employee-agent.html`.
2. Import only the leave subset and record hashes/licence provenance.
3. Define fixtures, the permission manifest, and the request state machine.
4. Write the first end-to-end smoke test before workflow code.
5. Implement the selected vertical slice through small tested iterations.

## 8. Open decisions

- Whether v1 supports only US leave or one additional jurisdiction.
- Whether manager approval is a required state transition or only an informational manager view.
- Which LLM provider and model form the retrieval/extraction baseline.

## 9. Target structure

`agents/` workflow coordination; `tools/` typed retrieval and state operations; `llm/` model client; `prompts/` versioned prompts; `schemas/` data models; `evals/` evaluation; `tests/` checks; `data/` corpus and provenance; `docs/` specs.

## 10. Definition of done for v1

- [ ] `pytest` passes.
- [ ] `pytest -m smoke` demonstrates the full employee-to-manager flow.
- [ ] Retrieval never sends a prohibited document fragment to the model.
- [ ] The same request has correct employee, manager, and HR projections.
- [ ] Submission requires explicit confirmation and is idempotent.
- [ ] Answers cite allowed source material; unsupported eligibility is escalated.
- [ ] `README.md` documents the data licence, local-only workflow, and known limits.
