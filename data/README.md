# Data plan

The source is the already frozen GitLab Handbook HR subset at:

`/home/petr/projects/ai/corporate-knowledge-assistant/data/handbook/`

It contains 47 Markdown files (about 1.1 MB) from `total-rewards`, `hiring`, and `people-policies`, distributed under the GitLab Handbook MIT licence. The original project records the source repository as `gitlab.com/gitlab-com/content-sites/handbook.git`.

The first workflow uses only leave-of-absence material, especially:

- `people-policies/leave-of-absence/_index.md`
- `people-policies/leave-of-absence/us.md`

The source tells US employees to request leave through Tilt via Okta. It supplies no usable public Tilt/Okta API and all documents are public. Therefore this project may model a local educational request lifecycle and a demonstration permission manifest, but cannot claim a real GitLab submission or real protected-document access control.

No corpus was copied or regenerated during project creation. Importing a narrowed immutable subset is the first implementation task after the specification is chosen.
