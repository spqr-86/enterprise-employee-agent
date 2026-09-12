.PHONY: sync check test check-corpus eval-smoke

sync:
	uv sync --locked

check:
	uv run --locked ruff check .
	uv run --locked ruff format --check .

test:
	uv run --locked pytest

check-corpus:
	uv run --locked python -m enterprise_employee_agent.knowledge.corpus

eval-smoke:
	uv run --locked pytest -m smoke
