# Offline-by-default demo image. No secrets and no database are baked in:
# the SQLite file lives in the /app/var volume, OPENROUTER_API_KEY comes from the environment.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.8 /uv /usr/local/bin/uv

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project

# The runtime reads data/ relative to the source tree, so the project is installed from /app.
COPY src ./src
COPY data ./data
RUN uv sync --locked --no-dev \
    && useradd --system --uid 10001 --home-dir /app app \
    && mkdir -p /app/var \
    && chown app /app/var

USER app
ENV DEMO_DATABASE_PATH=/app/var/demo.sqlite
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
    CMD ["/app/.venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/identity', timeout=2)"]

CMD ["/app/.venv/bin/uvicorn", "enterprise_employee_agent.web.server:create_app_from_env", \
     "--factory", "--host", "0.0.0.0", "--port", "8000"]
