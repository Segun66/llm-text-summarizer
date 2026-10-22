# LLM Text Summarizer

[![CI](https://github.com/Segun66/llm-text-summarizer/actions/workflows/ci.yml/badge.svg?branch=feature%2Fllm-summarizer)](https://github.com/Segun66/llm-text-summarizer/actions/workflows/ci.yml)

Учебный Python backend для итоговой аттестации: HTTP API принимает текст,
получает краткое содержание через GigaChat и возвращает JSON.
Автор GitHub: [Segun66](https://github.com/Segun66).
Репозиторий: [llm-text-summarizer](https://github.com/Segun66/llm-text-summarizer).

## 1. Назначение

Сервис помогает сокращать статьи, заметки и другие тексты с сохранением
основных фактов. Проект демонстрирует разделение слоёв, асинхронную работу
с внешним API, валидацию, обработку ошибок, кеширование, тестирование и CI.

## 2. Возможности

- POST /summarize с ограничением длины результата в символах.
- Проверка обязательного текста и параметров через Pydantic v2.
- Раздельные system/user prompts, инструкция не добавлять выдуманных фактов.
- OAuth-авторизация GigaChat, кеш токена, HTTP connection pool.
- Ограниченные retry временных ошибок и явный fallback при недоступности LLM.
- Локальный потокобезопасный TTL/LRU-кеш только успешных результатов.
- GET /health без вызова LLM, Swagger UI и OpenAPI.
- Структурированные JSON-логи с request_id без тел запросов и секретов.

## 3. Архитектура и структура директорий

~~~text
llm-text-summarizer/
├── .github/workflows/ci.yml
├── .env.example
├── .gitignore
├── main.py
├── pyproject.toml
├── README.md
├── TESTING.md
├── app/
│   ├── api/              # Маршруты, DI и request_id middleware
│   ├── config/           # pydantic-settings
│   ├── llm/              # Protocol, GigaChat, prompts и lifecycle
│   ├── models/           # Pydantic-схемы
│   ├── services/         # SummarizationService и интерфейс/реализация кеша
│   └── utils/            # Постобработка, ошибки, нормализация и JSON-логи
├── scripts/
│   └── check_gigachat.py # Ручная проверка с ключом через скрытый ввод
├── tests/                # Unit- и HTTP-тесты с моками
└── docs/                 # Подробные описания архитектуры, конфигурации и CI
~~~

В Python-пакетах также есть __init__.py.

~~~mermaid
flowchart LR
    A["HTTP + Pydantic"] --> B["SummarizationService"]
    B --> C{"TTL-кеш"}
    C -->|hit| H["success, cached=true"]
    C -->|miss| D["prompts.py → LLMClient"]
    D -->|успех| E["Постобработка"]
    E --> F["Запись в кеш"]
    F --> G["success, cached=false"]
    D -->|временная недоступность после retry| I["fallback, cached=false"]
~~~

API определяет HTTP-статусы; сервис не зависит от FastAPI и HTTP-кодов.
LLM и кеш подключаются через Protocol. Ошибки программирования не превращаются
в fallback. Подробности: [ARCHITECTURE.md](docs/ARCHITECTURE.md).

## 4. Технологии

Python 3.11+, FastAPI, Pydantic v2, pydantic-settings, httpx, Tenacity,
Uvicorn, pytest, Ruff, стандартный logging и GitHub Actions.
Зависимости и ограничения версий объявлены в pyproject.toml.
База данных, Redis, Docker и SDK GigaChat не требуются.

## 5. Требования для запуска

- Python 3.11 или новее с pip и модулем venv.
- Git для клонирования; curl для ручных HTTP-проверок.
- Для настоящей генерации: доступ к GigaChat API, ключ авторизации,
  подходящие модель/scope и доверенная цепочка TLS-сертификатов.
- Для автоматических тестов ключ и доступ к GigaChat не нужны.

Все последующие команды выполняются из корня репозитория.
После активации окружения команда python должна указывать на .venv.
В Windows можно всегда использовать .\.venv\Scripts\python.exe,
в Linux/macOS — .venv/bin/python, без активации.

## 6. Клонирование с GitHub

Текущая опубликованная ветка с проектом — feature/llm-summarizer:

~~~bash
git clone --branch feature/llm-summarizer https://github.com/Segun66/llm-text-summarizer.git
cd llm-text-summarizer
~~~

До объединения проекта в main не используйте main вместо этой ветки.
Бейдж в начале README показывает результат именно feature/llm-summarizer.

## 7. Виртуальное окружение

~~~bash
python -m venv .venv
~~~

Windows PowerShell:

~~~powershell
.\.venv\Scripts\Activate.ps1
~~~

Linux/macOS:

~~~bash
source .venv/bin/activate
~~~

Если политика PowerShell запрещает Activate.ps1, активация не обязательна:
используйте полный путь к .venv\Scripts\python.exe в командах ниже.

## 8. Установка зависимостей

Для разработки и проверки преподавателем:

~~~bash
python -m pip install -e ".[dev]"
python -m pip check
~~~

Для запуска без pytest/Ruff достаточно python -m pip install -e .
В CI проверяется обычная установка python -m pip install ".[dev]".
Глобальная установка зависимостей не требуется.

## 9. Настройка окружения

Создавайте .env из примера только если .env ещё отсутствует.
Существующий файл с секретами не перезаписывайте.

Windows PowerShell:

~~~powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
~~~

Linux/macOS:

~~~bash
if [ ! -e .env ]; then cp .env.example .env; fi
~~~

Заполните GIGACHAT_CREDENTIALS локально ключом авторизации из кабинета
GigaChat (Base64 от Client ID:Client Secret), без префикса Basic.
Пустое поле в примере — место для заполнения, с ним приложение не запустится.

| Переменная | Значение / назначение |
| --- | --- |
| APP_ENV | dev или prod, по умолчанию dev |
| LOG_LEVEL | DEBUG, INFO, WARNING, ERROR, CRITICAL; по умолчанию INFO |
| GIGACHAT_CREDENTIALS | Обязательный секрет; реального значения в примере нет |
| GIGACHAT_AUTH_URL | Обязательный полный HTTPS URL OAuth из .env.example |
| GIGACHAT_COMPLETIONS_URL | Обязательный полный HTTPS URL chat completions v1 |
| GIGACHAT_MODEL | По умолчанию GigaChat; проверьте доступ своей учётной записи |
| GIGACHAT_SCOPE | По умолчанию GIGACHAT_API_PERS |
| GIGACHAT_TIMEOUT_SECONDS | 30 секунд на сетевую фазу отдельной попытки |
| GIGACHAT_MAX_ATTEMPTS | 1–3 попытки, по умолчанию 3 |
| GIGACHAT_RETRY_MIN_SECONDS / GIGACHAT_RETRY_MAX_SECONDS | Множитель backoff 0.5 / предел 4 секунды |
| GIGACHAT_MAX_TOKENS | По умолчанию 512; это токены, а не символы max_length |
| GIGACHAT_CACHE_TTL_SECONDS | По умолчанию 300 секунд |
| GIGACHAT_CACHE_MAX_ENTRIES | По умолчанию 128 записей |
| GIGACHAT_CA_BUNDLE | Необязательный путь к PEM-файлу доверенных CA |

GIGACHAT_AUTH_KEY поддерживается как совместимое старое имя credentials.
Приоритет: аргументы Settings → окружение процесса → .env → defaults.
APP_ENV не выбирает автоматически .env.dev или .env.prod.
URL не содержат секретов, query и fragment. Проверка TLS всегда включена.
.env, .env.*, .venv, кеши и файлы ключей исключены .gitignore;
исключение — безопасный шаблон .env.example.

Подробности: [CONFIGURATION.md](docs/CONFIGURATION.md),
[GIGACHAT.md](docs/GIGACHAT.md). Не публикуйте ключ, .env или скриншоты с секретами.

## 10. Запуск FastAPI одной командой

После установки и заполнения .env:

~~~bash
python -m uvicorn main:app --reload
~~~

Без активации в PowerShell:

~~~powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --reload
~~~

Адрес по умолчанию: http://127.0.0.1:8000.
Для режима без автоматической перезагрузки уберите --reload.
Остановка: Ctrl+C. При неверной конфигурации запуск завершается ошибкой.

## 11. Swagger UI и эндпоинты

- [Swagger UI](http://127.0.0.1:8000/docs).
- [OpenAPI JSON](http://127.0.0.1:8000/openapi.json).

| Метод | Путь | Назначение |
| --- | --- | --- |
| GET | /health | Проверка процесса, без запроса к LLM |
| POST | /summarize | Сокращение текста, кеш или контролируемый fallback |

В Swagger выберите POST /summarize → Try it out → задайте JSON → Execute.

Тело запроса:

~~~json
{"text":"Компания запустила сервис сокращения статей. Он выделяет основные факты.","max_length":300}
~~~

text — обязательная строка, после trim 1–10000 символов.
max_length — строго целое число 50–1000, по умолчанию 300.
Лишние поля запрещены; bool, float и строка вместо целого также отклоняются.
Результат содержит summary, status (success/fallback), cached (boolean).
В обычных ответах присутствует X-Request-ID; его можно передать как UUID.

Health сообщает только о процессе: GigaChat может быть недоступен при health=ok.
Для завершения старта приложения всё равно нужна валидная конфигурация.

## 12. Примеры curl

В bash/zsh:

~~~bash
curl -i http://127.0.0.1:8000/health
curl -i http://127.0.0.1:8000/summarize -H "Content-Type: application/json" -d '{"text":"Компания запустила сервис сокращения статей. Он выделяет основные факты.","max_length":100}'
curl -i http://127.0.0.1:8000/summarize -H "Content-Type: application/json" -d '{"text":"   "}'
~~~

В PowerShell используйте curl.exe вместо возможного алиаса curl.
Чтобы корректно передать UTF-8 и JSON без проблем с кавычками:

~~~powershell
$requestPath = Join-Path ([System.IO.Path]::GetTempPath()) ("llm-request-" + [guid]::NewGuid() + ".json")
$payload = @{ text = 'Компания запустила сервис сокращения статей. Он выделяет основные факты.'; max_length = 100 } | ConvertTo-Json -Compress
[System.IO.File]::WriteAllText($requestPath, $payload, [System.Text.UTF8Encoding]::new($false))
curl.exe -i http://127.0.0.1:8000/health
curl.exe -i http://127.0.0.1:8000/summarize -H "Content-Type: application/json" --data-binary "@$requestPath"
Remove-Item -LiteralPath $requestPath
~~~

## 13. Успешные ответы и ошибки

Health, HTTP 200:

~~~json
{"status":"ok"}
~~~

Пример генерации, HTTP 200 (содержание зависит от модели):

~~~json
{"summary":"Компания запустила сервис, который сокращает статьи и выделяет основные факты.","status":"success","cached":false}
~~~

Повтор до истечения TTL, HTTP 200:

~~~json
{"summary":"Компания запустила сервис, который сокращает статьи и выделяет основные факты.","status":"success","cached":true}
~~~

Пустой текст после trim, HTTP 422:

~~~json
{"detail":[{"type":"string_too_short","loc":["body","text"],"msg":"String should have at least 1 character","input":"   ","ctx":{"min_length":1}}]}
~~~

При недоступности провайдера, HTTP 503:

~~~json
{"summary":"Компания запустила сервис сокращения статей. Он выделяет основные факты.","status":"fallback","cached":false}
~~~

Это начало исходного текста, ограниченное max_length, а не результат LLM.

| Ситуация | HTTP | Ответ |
| --- | --- | --- |
| Успех или cache hit | 200 | summary, status=success, cached |
| Ошибка входной валидации | 422 | detail: список ошибок |
| Провайдер отклонил вход (400/413/422) | 422 | detail: безопасная строка |
| Авторизация провайдера (401/403), неверный JSON, пустой/незавершённый ответ | 502 | detail: безопасная строка |
| Временная недоступность после retry | 503 | summary, status=fallback, cached=false |
| Неожиданная ошибка программирования | 500 | Стандартная ошибка сервера, без fallback |

Пример ошибки авторизации GigaChat, HTTP 502:

~~~json
{"detail":"Ошибка авторизации сервиса в LLM."}
~~~

Текст валидационной ошибки может включать входное поле в HTTP-ответе;
он не записывается приложением в логи. Примеры success выше иллюстративные,
а не результат настоящего обращения к GigaChat во время подготовки README.

## 14. Timeout, retry и fallback

Tenacity выполняет максимум три попытки на один запрос к провайдеру,
с exponential backoff и jitter. Повторяются timeout, network error, 429 и 5xx.
OAuth и генерация имеют отдельные бюджеты попыток.
400/401/403, ошибки входа, невалидный JSON, пустой или незавершённый ответ
не повторяются. Ошибка авторизации не запускает новый OAuth-цикл.

После исчерпания временных ошибок сервис возвращает явный fallback/503.
Клиент должен проверять и HTTP-статус, и поле status.
Fallback не кешируется. Ошибки программирования не маскируются под fallback.

Timeout относится к сетевым фазам попытки, а не к общему времени HTTP-запроса.
Повтор POST может вызвать повторную генерацию и расход квоты.
Retry-After отдельно не обрабатывается.

## 15. Кеширование и TTL

Ключ: SHA-256 от нормализованного текста, max_length, модели и версии промпта.
Нормализация сводит все пробельные последовательности к одному пробелу;
регистр и пунктуация сохраняются. В промпт передаётся тот же текст.
Секреты не участвуют в ключе.

TTL по умолчанию 300 секунд, отсчитывается monotonic clock от записи.
Чтение не продлевает TTL. Просроченная запись считается промахом.
Размер ограничен 128 записями по умолчанию; вытеснение — LRU.
Короткие операции защищены threading.Lock. Сохраняются только успешные,
непустые и обработанные результаты; ошибки и fallback не кешируются.

Кеш локален для одного процесса, сбрасывается при перезапуске.
У каждого worker свой кеш. Параллельные промахи не объединяются в один LLM-вызов.

## 16. pytest и Ruff

~~~bash
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
~~~

Команда pytest -q также работает: корень проекта включён в pythonpath.
HTTP-тесты используют FastAPI TestClient и моки httpx; стандартные реальные
HTTP-транспорты в тестах блокируются. Retry sleep отключён, TTL проверяется
управляемыми часами. Настоящий .env и рабочий ключ для тестов не нужны.

На коммите 39cfe1a локально подтверждены 248 passed, 0 skipped, 0 failed
и успешный Ruff; удалённый CI также успешен. Текущие результаты подготовки
документации приведены в [TESTING.md](TESTING.md).
Есть известное предупреждение Starlette об устаревшем использовании httpx
в TestClient; оно не скрыто и не приводит к падению тестов.

## 17. GitHub Actions

Workflow: [.github/workflows/ci.yml](.github/workflows/ci.yml).
Запуск: push в main и feature/**, pull_request в main.
Runner — ubuntu-latest, Python 3.11; pip cache привязан к pyproject.toml.
Проверяются установка обычного пакета, pip check, импорт main.app вне checkout,
Ruff, форматирование и pytest. Ошибка шага приводит к failure job.
Secrets GigaChat в CI не используются.

Подтверждённый [успешный запуск для 39cfe1a](https://github.com/Segun66/llm-text-summarizer/actions/runs/39620146660)
проверен через GitHub API. Бейдж отражает последующие запуски выбранной ветки,
а не гарантирует успех любых будущих изменений.
Как воспроизвести проверку на GitHub: [CI.md](docs/CI.md) и [TESTING.md](TESTING.md).

## 18. Известные ограничения

- Нет chunking: 10000 символов не гарантируют попадание в контекст модели.
- Качество и фактическая точность LLM не гарантируются; постобработка
  нормализует пробелы и длину, но не проверяет факты. Усечение может обрезать фразу.
- Нет общего deadline, отдельной обработки Retry-After и single-flight промахов кеша.
- Нет распределённого кеша, хранения истории, БД и очереди.
- /health не проверяет готовность GigaChat.
- API не реализует авторизацию пользователя и собственный rate limiting.
- README описывает локальный запуск; production-деплой и нагрузочные испытания
  выходят за рамки текущего проекта.
- Реальный GigaChat проверяется отдельно: нужны ключ, квота и доверие TLS.
  Автоматические тесты не доказывают доступность внешнего провайдера.

## Документация для проверки преподавателем

- [TESTING.md](TESTING.md) — сценарии демонстрации и результаты проверок.
- [ARCHITECTURE.md](docs/ARCHITECTURE.md) — слои и ошибки.
- [CONFIGURATION.md](docs/CONFIGURATION.md) — dev/prod и JSON-логи.
- [GIGACHAT.md](docs/GIGACHAT.md) — протокол и ручной безопасный ввод ключа.
- [TEST_COVERAGE.md](docs/TEST_COVERAGE.md) — аудит обязательных сценариев.
- [CI.md](docs/CI.md) — workflow и его проверка.

## Независимый итоговый аудит — 21 октября 2026 года

После добавления шести регрессионных случаев и исправления схемы OpenAPI 503:
254 passed, 0 skipped, 0 failed, 0 errors; одно предупреждение Starlette.
Ruff check и format проходят (44 Python-файла), pip check успешен.
Временным инструментом coverage измерены app/main: 445 statements и
86 branches, без пропусков (100%). Это не проверка настоящего GigaChat.
Uvicorn/curl повторно подтверждены: health/OpenAPI 200, валидация 422,
два offline fallback 503/cached=false.

Предыдущие цифры 248 относятся к проверкам до итогового аудита.
main уже опубликована, PR ещё нет; удалённый CI подтверждён для 39cfe1a,
текущие локальные изменения требуют нового запуска после публикации.
Полная матрица требований, проблемы и ручные шаги: [FINAL_AUDIT.md](docs/FINAL_AUDIT.md).
