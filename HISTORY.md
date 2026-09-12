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
