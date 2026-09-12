# Enterprise Employee Agent — backlog

This file is the prioritized initiative index until a GitHub remote and Issues exist. After an
initiative becomes an Issue, the Issue is authoritative for task status and acceptance criteria.

| Priority | Initiative | Why now | Depends on | Issue/milestone |
|---|---|---|---|---|
| P0 | Reconcile and bootstrap | Makes the documented workflow executable | Current spec/framework | #1 done via PR #2 |
| P0 | Corpus manifest | Gives retrieval a frozen, attributable input | Bootstrap | not yet filed |
| P0 | Workflow contract | Fixes identities, projections, commands and errors before code | Bootstrap | not yet filed |
| P0 | Micro-eval contract | Defines expected model behavior before tuning | Corpus manifest | not yet filed |
| P1 | Retrieval/answer baseline | Establishes measured knowledge behavior | Corpus and micro-eval | not yet filed |
| P1 | Deterministic workflow | Proves access, confirmation, idempotency and persistence | Workflow contract | not yet filed |
| P1 | First vertical slice | Demonstrates the complete fake-adapter journey | Deterministic workflow | v0.1 |
| P1 | Integrated assistant | Connects measured knowledge behavior to the typed workflow | Baseline and vertical slice | v0.1 |
| P1 | Portfolio release | Adds interface, Docker, CI evidence and held-out evaluation | Integrated assistant | v0.1 |
| P3 | Development automation | Evaluates orchestration after the manual lifecycle is proven | Completed task cycles | later |
| P3 | Second workflow domain | Tests which abstractions really repeat | v0.1 evidence | later |
