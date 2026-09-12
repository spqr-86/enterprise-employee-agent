# Enterprise Employee Agent — backlog

This file is the prioritized initiative index until a GitHub remote and Issues exist. After an
initiative becomes an Issue, the Issue is authoritative for task status and acceptance criteria.

| Priority | Initiative | Why now | Depends on | Issue/milestone |
|---|---|---|---|---|
| P0 | Reconcile and bootstrap | Makes the documented workflow executable | Current spec/framework | #1 done via PR #2 |
| P0 | Corpus manifest | Gives retrieval a frozen, attributable input | Bootstrap | #5 ready · v0.1 |
| P0 | Workflow contract | Fixes identities, projections, commands and errors before code | Bootstrap | #6 ready · v0.1 |
| P0 | Micro-eval contract | Defines expected model behavior before tuning | #5 and #6 | #7 draft · v0.1 |
| P1 | Retrieval/answer baseline | Establishes measured knowledge behavior | #5 and #7 | #8 draft · v0.1 |
| P1 | Authorization and projections | Prevents cross-role and cross-user disclosure | #6 | #9 draft · v0.1 |
| P1 | State and audit storage | Makes the bounded leave lifecycle persistent and atomic | #6 | #10 draft · v0.1 |
| P1 | Confirmation and idempotency | Prevents stale or duplicate submission | #6 and #10 | #11 draft · v0.1 |
| P1 | First vertical slice | Demonstrates the complete fake-adapter journey | #9, #10 and #11 | #12 draft · v0.1 |
| P1 | Integrated assistant | Connects measured knowledge behavior to the typed workflow | #8 and #12 | #13 draft · v0.1 |
| P1 | Demo interface | Exposes evidence, identity, confirmation and role views | #13 | #14 draft · v0.1 |
| P1 | Reproducible package | Adds Docker, offline CI, README and clean-clone evidence | #14 | #15 draft · v0.1 |
| P1 | Release evaluation | Publishes held-out results, failures, limits and release decision | #7, #13 and #15 | #16 draft · v0.1 |
| P3 | Development automation | Evaluates orchestration after the manual lifecycle is proven | Completed task cycles | later |
| P3 | Second workflow domain | Tests which abstractions really repeat | v0.1 evidence | later |
