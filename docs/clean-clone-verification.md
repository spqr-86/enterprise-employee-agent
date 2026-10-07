# Clean-clone verification — Issue #15

- Date: 2026-10-07 (UTC 10:16–10:20)
- Revision: `da96e6322fe2fc1bb16fb5ef158c0fb4a64bcdf8` (branch `chore/15-docker-release`)
- Host: Linux 6.12, Docker 29.8.0, Docker Compose v5.5.1, uv 0.12.8
- Source: fresh `git clone` from GitHub into an empty directory; the local image was removed
  first, so the build ran from the clone.

## Docker path

| Step | Command | Observed |
|---|---|---|
| Build and start | `docker compose up --build --detach --wait` | container `healthy` |
| Page responds | `GET /identity` | 200 |
| Create a draft as `employee-alice` | `POST /identity`, then `POST /requests` (form fields, same-origin header, idempotency key ≥ 8 chars) | 303 → `/requests/leave-b4e89f19…` |
| Restart | `docker compose restart` | the request is still listed in `/requests` |
| Recreate container | `docker compose down`, `docker compose up -d --wait` | the request is still listed |
| Drop the volume | `docker compose down -v`, `up` | the list is empty |
| Runtime user | `docker compose exec demo id -un` | `app` (non-root, uid 10001) |
| Image contents | `ls -a /app` in the image | `.venv README.md data pyproject.toml src uv.lock var`; no `.env`, no database |

A first attempt used the idempotency key `cc1` and got 422 "The request data is invalid": the
key pattern requires 8–200 characters. That is the validation working, not a packaging defect.

## Local path

| Command | Observed |
|---|---|
| `uv sync --locked` | ok |
| `make check` | Ruff clean, 77 files formatted |
| `make test` | 464 passed |
| `make eval-smoke` | 10 passed |

## Secrets

`git grep` for OpenRouter key and `api_key = "…"` patterns finds only test placeholders in
`docs/superpowers/plans/` (`sk-or-test-secret-value`, `sk-test-not-used`). `.env.example` has an
empty `DEMO_OPENROUTER_API_KEY` (compose maps it to `OPENROUTER_API_KEY` inside the container); `.env` is git- and docker-ignored.

## Not covered

- No live-mode run (needs a key and spend).
- The README demo flow beyond draft creation was checked by the existing UI journey tests
  (`tests/integration/test_demo_ui_journey.py`), not by hand in a browser.
