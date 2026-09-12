.PHONY: sync check test eval-smoke

sync:
	uv sync --locked

check:
	uv run --locked ruff check .
	uv run --locked ruff format --check .

test:
	uv run --locked pytest

eval-smoke:
	uv run --locked pytest -m smoke
