# LLM Text Summarizer

HTTP API для краткого содержания текста: Python 3.11+, FastAPI, Pydantic v2,
httpx и GigaChat REST API. База данных и официальный SDK не требуются.

## Установка и запуск

Команды PowerShell из корня проекта:

~~~powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
~~~

Заполните `GIGACHAT_CREDENTIALS` в `.env` ключом авторизации из кабинета GigaChat
(Base64 от Client ID:Client Secret, без префикса `Basic`). Проверьте полные URL,
модель и scope своего подключения. Переменные окружения имеют приоритет над `.env`.
Непустой ключ и оба HTTPS URL обязательны: приложение проверяет их при старте.

~~~powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --reload
~~~

Swagger UI: http://127.0.0.1:8000/docs. Для запуска без инструментов разработки
достаточно `pip install -e .`. В production запускайте без `--reload`.

Пример запроса в PowerShell:

~~~powershell
$body = @{ text = 'Компания запустила новый сервис. Он помогает сокращать длинные статьи и выделять основные факты.' } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/summarize -ContentType 'application/json; charset=utf-8' -Body ([System.Text.Encoding]::UTF8.GetBytes($body))
~~~

Контракт:

~~~json
{"text": "Текст для сокращения", "max_length": 300}
~~~

Ответ HTTP 200:

~~~json
{"summary": "Краткое содержание текста.", "status": "success", "cached": false}
~~~

Поле `text` — обязательная строка из 1–10 000 символов после trim.
Поле `max_length` — строго целое число от 50 до 1000, по умолчанию 300;
это верхний предел длины результата в символах, включая многоточие.
Пустые строки, неверные типы, лишние поля и выход за границы возвращают HTTP 422.
Модель получает ограничение длины в промпте; сервис дополнительно ограничивает результат.
При недоступности модели или таймауте сервис возвращает нормализованное начало
исходного текста: HTTP 503, `status: "fallback"`. Успех: HTTP 200, `status: "success"`.
Успешные результаты сохраняются в локальный для одного процесса TTL/LRU-кеш.
По умолчанию TTL — 300 секунд, максимальный размер — 128 записей:

~~~dotenv
GIGACHAT_CACHE_TTL_SECONDS=300
GIGACHAT_CACHE_MAX_ENTRIES=128
~~~

Время жизни считается через monotonic clock от последней записи, без продления
при чтении. После истечения запись удаляется; на промахе выполняется новый LLM-вызов.
Ключ — SHA-256 от нормализованного текста (все последовательности пробельных
символов заменены одним пробелом), max_length, имени модели и версии промпта.
Регистр и пунктуация сохраняются. В LLM передаётся тот же нормализованный текст.
Секреты в ключ не входят. Повторный запрос до истечения TTL возвращает
`cached: true`, без обращения к LLM.

Fallback и ошибки не кешируются. Доступ к записям защищён блокировкой;
при заполнении вытесняется наименее недавно использованная запись (LRU),
просроченные записи удаляются при чтении и записи. Кеш сбрасывается при перезапуске.
У каждого worker свой кеш: между процессами данные не разделяются.
Повторяются только timeout, сетевые ошибки, 429 и 5xx (максимум 3 попытки).
401/403 не повторяются и возвращают detail/502 вместо прежнего fallback/503:
ошибка авторизации провайдера требует исправления ключа или доступа.
Ошибки программирования не превращаются в fallback.
Фактическая точность сгенерированного содержания зависит от модели.
Автоматическое разбиение длинного текста на части не реализовано: размер в символах
не равен числу токенов, и провайдер может отклонить превышение контекста.

## Конфигурация

Все параметры имеют префикс `GIGACHAT_`; примеры находятся в `.env.example`.
Полные URL задаются отдельно для OAuth и chat completions, в коде URL по умолчанию нет.
Scope по умолчанию — `GIGACHAT_API_PERS`, модель — `GigaChat`.
Для корпоративного подключения укажите scope и модель своего аккаунта.

Проверка TLS всегда включена. При необходимости задайте `GIGACHAT_CA_BUNDLE`
путём к PEM-файлу доверенных CA. Если файл не указан, используется стандартное
хранилище Python SSL. Ошибки пути или конфигурации обнаруживаются при старте.
Не добавляйте `.env`, ключи и сертификаты с закрытыми ключами в репозиторий.

По умолчанию: timeout 30 секунд на сетевую фазу httpx, до 3 попыток на один запрос
к провайдеру, экспоненциальные задержки со случайным разбросом до 4 секунд,
выход до 512 токенов. Общий вызов API может длиться дольше timeout из-за OAuth,
повторов и ожидания блокировки токена. Повтор POST после сетевого сбоя может
привести к повторной генерации и списанию токенов.

## Проверки

~~~powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
~~~

Тесты не требуют настоящего ключа и сетевого доступа: используется
`httpx.MockTransport` / `ASGITransport`. Проверяются весь поток запроса,
валидация, кеш и обновление токена, конкурентный доступ, повторы, ошибки HTTP,
таймауты, некорректный JSON, незавершённая генерация, пустой результат,
fallback, ограничения длины и независимость `/health` от бизнес-сервиса.

Подробности слоёв, поток данных и обработка ошибок: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Документация провайдера

- [Авторизация и адреса GigaChat API](https://developers.sber.ru/docs/ru/gigachat/api/reference/rest/gigachat-api).
- [Генерация ответа](https://developers.sber.ru/docs/ru/gigachat/api/reference/rest/post-chat).

## Проверка HTTP API через curl

В PowerShell используйте `curl.exe` вместо `curl`, если имя занято алиасом.
Для UTF-8 JSON в Windows также можно сохранить тело в файл и передать
`--data-binary @request.json`.

~~~bash
curl -i http://127.0.0.1:8000/health
curl -i http://127.0.0.1:8000/summarize -H "Content-Type: application/json" -d '{"text":"FastAPI validates requests. The service summarizes the text.","max_length":100}'
curl -i http://127.0.0.1:8000/summarize -H "Content-Type: application/json" -d '{"text":"   "}'
~~~

Health, HTTP 200:

~~~json
{"status":"ok"}
~~~

Пример успешной генерации, HTTP 200 (содержание зависит от модели):

~~~json
{"summary":"The service validates and summarizes text.","status":"success","cached":false}
~~~

Fallback для этого же запроса при недоступности модели, HTTP 503:

~~~json
{"summary":"FastAPI validates requests. The service summarizes the text.","status":"fallback","cached":false}
~~~

Пустой текст после trim, HTTP 422:

~~~json
{"detail":[{"type":"string_too_short","loc":["body","text"],"msg":"String should have at least 1 character","input":"   ","ctx":{"min_length":1}}]}
~~~

Подключение и безопасная ручная проверка с ключом: [docs/GIGACHAT.md](docs/GIGACHAT.md).

Настройки APP_ENV/LOG_LEVEL, dev/prod и безопасные JSON-логи: [docs/CONFIGURATION.md](docs/CONFIGURATION.md).

Аудит обязательных сценариев и TestClient-проверки: [docs/TEST_COVERAGE.md](docs/TEST_COVERAGE.md).

GitHub Actions CI: [docs/CI.md](docs/CI.md).
