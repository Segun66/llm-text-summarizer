# Интеграция с GigaChat

Формат проверен по официальной документации и OpenAPI 21 октября 2026 года:

- [Авторизация](https://developers.sber.ru/docs/ru/gigachat/api/reference/rest/gigachat-api).
- [Получение токена](https://developers.sber.ru/docs/ru/gigachat/api/reference/rest/post-token).
- [Chat completions](https://developers.sber.ru/docs/ru/gigachat/api/reference/rest/post-chat).
- [Официальная OpenAPI-схема](https://developers.sber.ru/docs/files/openapi/gigachat/api.yml).

## Подтверждённый протокол

OAuth: POST `https://ngw.devices.sberbank.ru:9443/api/v2/oauth`.
Ключ авторизации из кабинета (Base64 от Client ID:Client Secret) передаётся
в заголовке `Authorization: Basic <ключ>`; `RqUID` — UUID4.
Тело — form-urlencoded с полем `scope`. Ответ содержит `access_token` и
`expires_at`. В OpenAPI единица измерения expires_at — миллисекунды Unix timestamp.

Генерация: POST `https://api.giga.chat/v1/chat/completions`.
Заголовок — `Authorization: Bearer <access_token>`; тело JSON:
`model`, `messages` с отдельными ролями `system` и `user`,
`max_tokens`, `temperature`, `stream: false`.
Текст ответа находится в `choices[0].message.content`;
клиент принимает только завершённый ответ с `finish_reason: stop`.
Это адаптер формата v1; замена URL на v2 без изменения схемы не поддерживается.

Все URL берутся из конфигурации. Приведённые адреса находятся только в
документации и .env.example, в Python-коде адресов провайдера по умолчанию нет.
Название модели и scope должны соответствовать доступу конкретного аккаунта.

## Переменные окружения

| Переменная | Обязательность | Значение |
| --- | --- | --- |
| APP_ENV | По умолчанию dev | Режим dev или prod |
| LOG_LEVEL | По умолчанию INFO | Уровень структурированных логов |
| GIGACHAT_CREDENTIALS | Обязательна для приложения | Ключ авторизации без префикса Basic |
| GIGACHAT_AUTH_URL | Обязательна | Полный HTTPS URL OAuth |
| GIGACHAT_COMPLETIONS_URL | Обязательна | Полный HTTPS URL v1 chat completions |
| GIGACHAT_MODEL | По умолчанию GigaChat | Модель, доступная вашему аккаунту |
| GIGACHAT_SCOPE | По умолчанию GIGACHAT_API_PERS | Scope аккаунта; также предусмотрены B2B/CORP |
| GIGACHAT_TIMEOUT_SECONDS | По умолчанию 30 | Таймаут каждой сетевой фазы каждой попытки |
| GIGACHAT_MAX_ATTEMPTS | По умолчанию 3 | Максимальное число попыток одного HTTP-запроса: 1–3 |
| GIGACHAT_RETRY_MIN_SECONDS | По умолчанию 0.5 | Множитель экспоненциальной задержки |
| GIGACHAT_RETRY_MAX_SECONDS | По умолчанию 4 | Верхний предел задержки |
| GIGACHAT_MAX_TOKENS | По умолчанию 512 | Ограничение выходных токенов, отдельно от max_length |
| GIGACHAT_CACHE_TTL_SECONDS | По умолчанию 300 | TTL успешных результатов в секундах, конечное число > 0 |
| GIGACHAT_CACHE_MAX_ENTRIES | По умолчанию 128 | Положительное ограничение числа записей локального кеша |
| GIGACHAT_CA_BUNDLE | Необязательна | PEM-файл доверенных CA |

Settings читает .env; переменные окружения имеют приоритет. Секрет хранится
в SecretStr. Не публикуйте .env и не передавайте ключ в командной строке.

## Жизненный цикл и ошибки

`LLMClient` — Protocol с методом `async generate(messages) -> str`.
Сервис формирует сообщения через prompts.py и вызывает этот интерфейс;
в unit-тестах используется fake LLM. Метод summarize(text, max_length)
сохранён у GigaChatClient для прямых проверок интеграции.

`open_gigachat(settings)` создаёт SSLContext с проверкой цепочки и имени хоста,
открывает один httpx.AsyncClient и закрывает его при обычном выходе и исключении.
FastAPI использует этот контекст в lifespan. `GigaChatClient` не закрывает
переданный ему извне AsyncClient: им владеет вызывающий код.
Сетевой timeout берётся из Settings даже при внешнем HTTP-клиенте.
Редиректы не выполняются, чтобы ключи не пересылались на другой адрес.

Кеш OAuth-токена защищён asyncio.Lock. Обновление происходит за 30 секунд
до истечения срока. Ответы 401/403 не повторяются и не запускают новый OAuth-цикл.
У каждой попытки OAuth
собственный UUID4. Ошибки:

- Неверная авторизация: LLMAuthenticationError, отдельный подкласс LLMServiceError.
  Ошибки OAuth 400/401/403 и генерации 401/403 не повторяются и не дают fallback.
- 429 и 5xx: ограниченные повторы со случайной экспоненциальной задержкой;
  затем LLMRateLimitError (429) или LLMUnavailableError (5xx).
  Retry-After отдельно не обрабатывается.
- Сетевые ошибки: ограниченные повторы, затем LLMNetworkError.
  Ошибки локального протокола/программирования не повторяются.
- Таймауты: ограниченные повторы, затем LLMTimeoutError.
- Невалидный JSON, структура, пустой текст, непригодный токен или незавершённая
  генерация: LLMInvalidResponseError, без повторов.
- Генерация 400/413/422: LLMRequestError, без повторов.

Временные ошибки — LLMTimeoutError, LLMNetworkError и LLMRateLimitError —
наследуют LLMUnavailableError. Только они и 5xx проходят retry и затем дают
fallback/503. Лимит — максимум 3 попытки отдельно для OAuth и генерации;
Tenacity использует exponential backoff с full jitter.
LLMAuthenticationError и LLMInvalidResponseError превращаются в 502,
LLMRequestError — в 422. Ошибки программирования распространяются до HTTP 500.
Старые имена Provider* и InvalidProviderResponse оставлены как алиасы.

Изменение поведения: раньше ошибка авторизации давала fallback/503 и после 401
был ещё один OAuth-цикл. Теперь авторизация — постоянная ошибка с detail/502,
без повторов. Это ошибка подключения к провайдеру, а не авторизации пользователя
нашего API. Поля успешного ответа и fallback (summary/status/cached) не изменены.
Проверка напрямую через LLM-клиент позволяет отличить успешное подключение от fallback.

Промпты находятся в prompts.py. В system-сообщении указаны точность,
запрет выдуманных фактов и предел max_length в символах. Исходный текст
передаётся только в user-сообщении. Соблюдение длины дополнительно обеспечивается
постобработкой сервиса; содержательную точность промпт гарантировать не может.

Клиент не логирует ключи, токены, исходные тексты или ответы. При преобразовании
ошибок скрывается исходная цепочка исключений, чтобы ошибки валидации ответа
не печатали токен в traceback. Не включайте стороннее логирование HTTP-тел и заголовков.

## Ручная проверка с настоящим ключом

Создайте .env из .env.example и проверьте URL, scope, модель и CA.
В .env ключ можно оставить пустым: проверочный скрипт запросит его отдельно.

Из корня проекта в интерактивном терминале:

~~~powershell
.\.venv\Scripts\python.exe -m scripts.check_gigachat
~~~

Введите ключ в скрытом приглашении `GigaChat authorization key (hidden)`.
Ключ не попадёт в историю команд или аргументы процесса. Скрипт подставит
его в Settings только на время выполнения. Для проверки используются короткий
фиксированный текст и прямой вызов адаптера без fallback. Выполняются настоящие
запросы OAuth и генерации, возможен расход квоты.

Успех: `GigaChat integration OK.` и сгенерированный текст, exit code 0.
Ошибка: безопасное сообщение без сырых ответов, токенов и traceback, exit code 1.
При проблемах доверия настройте GIGACHAT_CA_BUNDLE; отключение TLS не предусмотрено.

## Автоматические тесты

~~~powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
~~~

Unit-тесты используют httpx.MockTransport и не выполняют реальных API-вызовов.
Проверяются OAuth, структура запросов, конфигурация, кеш/обновление токена,
повторы, таймауты, ошибки HTTP/JSON, пустой ответ, разделение промптов,
проверка TLS, закрытие HTTP-клиента и отсутствие секретов в логах/traceback.
