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
