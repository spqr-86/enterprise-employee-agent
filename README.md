# Enterprise Employee Agent

Учебный корпоративный помощник на данных GitLab Handbook. Он отвечает по HR-документам и ведёт один контролируемый workflow leave of absence: собирает недостающие сведения, показывает черновик, создаёт заявку после подтверждения и выдаёт каждой роли только разрешённую проекцию статуса.

Главная граница: **LLM интерпретирует запрос, код владеет доступами, валидацией, состоянием и
необратимыми действиями.** Модель не может сама авторизовать действие или изменить заявку.

```text
запрос сотрудника
→ structured intent
→ авторизация и проекция по роли
→ версионированный черновик (preview)
→ явное подтверждение
→ идемпотентная команда в SQLite-транзакции
→ audit event
```

## Статус

Сделано:

- typed workflow contracts, role-based access и проекции статуса для employee / manager / HR;
- version-bound confirmation и идемпотентные команды поверх атомарного SQLite workflow;
- grounded-ответы по HR-документам GitLab Handbook, встроенные в leave workflow;
- offline vertical slice: сквозной путь employee → HR → manager через публичные границы
  приложения, без сети;
- server-rendered demo UI (FastAPI + Jinja2), см. ниже;
- **464 теста** (`make test`), включая smoke-сценарии полного пути.

Ещё нет: Docker Compose и проверка с чистого клона (Issue #15), расширенный датасет и held-out
live-оценка с опубликованными результатами (Issue #16). Проект учебный, не production.

## Разработка

Требуется `uv`; нужная версия Python 3.12 устанавливается автоматически.

```bash
uv sync --locked
make check
make test
make eval-smoke
```

## Demo UI

`make demo` starts a minimal server-rendered demo (FastAPI + Jinja2) at
`http://127.0.0.1:8000`: switch between a synthetic employee/manager/HR identity and walk the
leave-request flow (ask, propose, draft, confirm, HR actions). The identity switcher is a demo
convenience only — it is not authentication, and the cookie it sets is unsigned by design.

By default the demo runs **offline**, answering from a fixed scripted fixture with no network
call. Setting `OPENROUTER_API_KEY` switches it to **live** mode against OpenRouter; live mode has
no budget guard, so only enable it locally and deliberately.

`DEMO_DATABASE_PATH` sets the SQLite file used for demo requests (default `var/demo.sqlite`).

## Документы

- [PLAN.md](PLAN.md) — живой план и принятые границы.
- [Спека](docs/spec-employee-agent.html) — варианты реализации и критерии приёмки.
- [DEVELOPMENT_FRAMEWORK.md](DEVELOPMENT_FRAMEWORK.md) — процесс разработки, архитектурные
  границы и проверки.
- [Данные](data/README.md) — состав и ограничения корпуса GitLab.
