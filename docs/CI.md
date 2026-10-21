# GitHub Actions CI

Workflow: [.github/workflows/ci.yml](../.github/workflows/ci.yml).
Он запускается на push в main и feature/**, а также на pull_request в main.
Используется GitHub-hosted ubuntu-latest и Python 3.11.

## Проверки

1. actions/checkout@v7.0.1 получает исходники с contents: read; git credentials
   не сохраняются для последующих команд.
2. actions/setup-python@v7.0.0 настраивает Python 3.11 и pip cache.
   Ключ кеша учитывает pyproject.toml; кешируются загрузки pip, не .venv.
3. python -m pip install ".[dev]" проверяет обычную установку проекта
   с runtime- и dev-зависимостями, включая сборку пакета.
4. Build check: pip check и импорт main.app из runner.temp, вне исходников,
   чтобы импортировать установленный пакет, а не случайную копию из checkout.
   Импорт не запускает lifespan и не требует GigaChat credentials.
5. Lint: ruff check . и ruff format --check .
6. Tests: pytest -q, с HTTP-моками и заблокированными реальными httpx-транспортами.

Ненулевой exit code установки, импорта, Ruff или pytest завершает job ошибкой.
continue-on-error и подавления exit code нет; для job установлен timeout 15 минут.
GitHub Secrets не используются, .env не создаётся и не выводится,
содержимое окружения и заголовки не печатаются. Фиктивные credentials задают
только существующие test fixtures. Бизнес-логика, pytest и Ruff не менялись.

Версии Actions сверены с официальными latest releases 21 октября 2026 года:

- [actions/checkout v7.0.1](https://github.com/actions/checkout/releases/tag/v7.0.1).
- [actions/setup-python v7.0.0](https://github.com/actions/setup-python/releases/tag/v7.0.0).
- [Документация pip cache](https://github.com/actions/setup-python#caching-packages-dependencies).

## Проверка на GitHub

После сохранения файлов в Git и отправки ветки feature/** откройте
[Actions](https://github.com/Segun66/llm-text-summarizer/actions) репозитория,
выберите CI и запуск для нужного commit SHA. Проверьте Build check, Lint и Tests:
все шаги должны завершиться успешно. Затем откройте PR в main и проверьте
вкладку Checks — событие pull_request запустит отдельную проверку.

При push в main workflow также запускается автоматически.
Перед первым запуском убедитесь, что GitHub Actions разрешены в настройках
репозитория. Workflow не содержит workflow_dispatch: ручная кнопка Run workflow
не предусмотрена. Для проверки используется push/PR.

Commit и push при локальной настройке не выполнялись. Удалённый запуск
нельзя считать успешным до подтверждения в GitHub Actions.
