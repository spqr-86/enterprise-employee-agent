.PHONY: sync check test check-corpus eval-smoke eval-offline eval demo

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

eval-offline:
	uv run --locked python -m enterprise_employee_agent.evals.run

eval:
	uv run --locked python -m enterprise_employee_agent.evals.live --confirm-spend

demo:
	uv run --locked uvicorn enterprise_employee_agent.web.server:create_app_from_env --factory --host 127.0.0.1 --port 8000
