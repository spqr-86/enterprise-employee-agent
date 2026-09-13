# Data plan

## Selection

The v0.1 corpus is the minimal company-wide and US leave-of-absence material needed by the first
workflow. `data/source/` contains exactly two byte-stable Markdown files:

| Stable ID | Title | Source path |
|---|---|---|
| `people-policies/leave-of-absence/_index.md` | Leave of Absence (company-wide) | `people-policies/leave-of-absence/_index.md` |
| `people-policies/leave-of-absence/us.md` | United States Leave of Absence Policies | `people-policies/leave-of-absence/us.md` |

The remaining 45 files of the original HR subset (`total-rewards`, `hiring`, other jurisdictions)
are intentionally excluded. `us.md` links to a broader parental-leave page that is not part of this
corpus; when a question needs it, the assistant must state that the source cannot establish the
answer instead of guessing. Broadening or refreshing the subset requires a deliberate data-scope
decision, not a routine change.

## Provenance and licence

- Upstream source: `git clone --depth 1 https://gitlab.com/gitlab-com/content-sites/handbook.git`.
- Frozen local snapshot: `spqr-86/corporate-knowledge-assistant`, revision
  `f7b8be0fca997b7f7571a0f63ca1ac75420e4bb6` (2026-07-16); the handbook files were added in
  `4ce1283a98dac1a50a4d5bb59f45791c9ac809b5` (2026-07-03). The upstream clone was shallow, so no
  upstream commit hash is recorded.
- Licence: MIT (GitLab B.V.), see [`HANDBOOK_LICENSE`](HANDBOOK_LICENSE). Reuse requires
  attribution to the GitLab Handbook.
- `data/manifest.json` records the source repository/revision, retrieval date, licence, stable
  document ID, source URL, repo path, SHA-256, byte size, and the `raw-v1` / `none-v1`
  normalization and chunking versions for every file.

Raw imports are immutable: source text is copied without modification and never normalized in
place. Derived fragments must be reproducible from these bytes.

## Reproduction and checks

Re-copy the two files from the frozen snapshot (bytes must not change; `cp -p` preserves them):

```bash
SNAP=/home/petr/projects/ai/corporate-knowledge-assistant/data/handbook
DEST=data/source/people-policies/leave-of-absence
mkdir -p "$DEST"
cp -p "$SNAP/people-policies/leave-of-absence/_index.md" "$DEST/_index.md"
cp -p "$SNAP/people-policies/leave-of-absence/us.md" "$DEST/us.md"
```

Validate the manifest against the exact source tree — this fails on a missing, extra, byte- or
hash-mismatched file:

```bash
make check-corpus
# equivalent: uv run --locked python -m enterprise_employee_agent.knowledge.corpus
```

`tests/unit/test_corpus_manifest.py` covers the same invariants, including stable-ID uniqueness and
untracked-file rejection, and validates the shipped corpus in CI.
