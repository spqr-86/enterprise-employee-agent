# Enterprise Employee Agent

Учебный корпоративный помощник на данных GitLab Handbook. Он отвечает по HR-документам и ведёт один контролируемый workflow leave of absence: собирает недостающие сведения, показывает черновик, создаёт заявку после подтверждения и выдаёт каждой роли только разрешённую проекцию статуса.

Это новый проект. Подход knowledge + typed workflow утверждён; installable Python-пакет и
локальные проверки собраны, продуктовая логика и данные ещё не перенесены. Реализация
продолжается с минимального US leave corpus и eval-набора из
[спеки](docs/spec-employee-agent.html).

## Разработка

Требуется `uv`; нужная версия Python 3.12 устанавливается автоматически.

```bash
uv sync --locked
make check
make test
make eval-smoke
```

## Документы

- [PLAN.md](PLAN.md) — живой план и принятые границы.
- [Спека](docs/spec-employee-agent.html) — варианты реализации и критерии приёмки.
- [DEVELOPMENT_FRAMEWORK.md](DEVELOPMENT_FRAMEWORK.md) — процесс разработки, архитектурные
  границы и проверки.
- [Данные](data/README.md) — состав и ограничения корпуса GitLab.
