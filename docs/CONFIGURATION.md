# Конфигурация и безопасные логи

Settings использует pydantic-settings: параметры конструктора имеют приоритет
над переменными процесса, переменные процесса — над .env, далее идут значения
по умолчанию. Читается только .env в текущей рабочей папке; APP_ENV не выбирает
автоматически .env.dev/.env.prod. Для production задайте окружение процесса
или используйте механизм секретов вашей платформы.

APP_ENV принимает dev/prod, LOG_LEVEL — DEBUG/INFO/WARNING/ERROR/CRITICAL.
Оба параметра по умолчанию: dev и INFO. Они не меняют контракт HTTP API.
APP_ENV записывается в структурированные логи. DEBUG не разрешает вывод тел,
заголовков, секретов или traceback.

## Примеры

Dev (.env, значение ключа нужно заполнить локально):

~~~dotenv
APP_ENV=dev
LOG_LEVEL=DEBUG
GIGACHAT_CREDENTIALS=
GIGACHAT_MODEL=GigaChat
GIGACHAT_AUTH_URL=https://ngw.devices.sberbank.ru:9443/api/v2/oauth
GIGACHAT_COMPLETIONS_URL=https://api.giga.chat/v1/chat/completions
GIGACHAT_TIMEOUT_SECONDS=30
GIGACHAT_MAX_ATTEMPTS=3
GIGACHAT_CACHE_TTL_SECONDS=300
GIGACHAT_CACHE_MAX_ENTRIES=128
~~~

Prod (окружение процесса; ключ передаётся отдельно через защищённый механизм):

~~~dotenv
APP_ENV=prod
LOG_LEVEL=INFO
GIGACHAT_CREDENTIALS=
GIGACHAT_MODEL=GigaChat
GIGACHAT_AUTH_URL=https://ngw.devices.sberbank.ru:9443/api/v2/oauth
GIGACHAT_COMPLETIONS_URL=https://api.giga.chat/v1/chat/completions
GIGACHAT_TIMEOUT_SECONDS=30
GIGACHAT_MAX_ATTEMPTS=3
GIGACHAT_CACHE_TTL_SECONDS=300
GIGACHAT_CACHE_MAX_ENTRIES=128
~~~

Пустой GIGACHAT_CREDENTIALS — только место для заполнения, приложение с ним
не запустится. Основное имя — GIGACHAT_CREDENTIALS. GIGACHAT_AUTH_KEY продолжает
работать для существующих установок. Если заданы оба имени в одном источнике,
выбирается GIGACHAT_CREDENTIALS. Ключ хранится как SecretStr; repr и JSON-дамп
Settings маскируют его. Строковое представление ошибок конфигурации скрывает
входные значения; вызов errors() вручную всё ещё может содержать исходный input,
поэтому ошибки конфигурации целиком в логи не передаются.

Полный перечень GIGACHAT_*: [GIGACHAT.md](GIGACHAT.md).
TLS всегда проверяется; при необходимости задайте GIGACHAT_CA_BUNDLE.
URL с credentials, query или fragment отклоняются: ключ передаётся только
в Authorization внутри LLM-клиента.

.env и .env.* исключены .gitignore; .env.example включён и не содержит реальных
секретов. Локальные секреты пользователя при этой доработке не читались и
не изменялись. Проверка исходников, тестов и документации по признакам JWT,
закрытых ключей и длинных литералов credentials не выявила совпадений.
Тестовые значения fixture/test/private — фиктивные маркеры, не рабочие ключи.
Такая проверка не доказывает отсутствие любого возможного формата секрета.

## JSON-логирование

Используется стандартный logging со StreamHandler (stderr) и JsonFormatter,
без дополнительных зависимостей. Настройка выполняется в lifespan приложения.
Собственные обработчики uvicorn/httpx/httpcore направляются в тот же форматтер.
Полный traceback, текст message/args сторонних логгеров и произвольные extra-поля
не выводятся: сторонние записи получают event=external_log, при наличии
исключения — только error_type. Это ограничивает детали диагностики ради
исключения случайного вывода payload или секретов.

Разрешённые поля: timestamp, level, app_env, request_id, event, stage,
duration_ms, cache_status, result_status, attempt, next_attempt,
retry_in_seconds, status_code, error_type. В логах нет пользовательского текста,
содержания результата, ключей кеша, URL, query-параметров, тел запросов и ответов,
API-ключей, access_token, Authorization и текстов исключений.

Примеры JSONL (длительности иллюстративные):

~~~json
{"timestamp":"2026-10-21T12:00:00+00:00","level":"INFO","app_env":"prod","request_id":"6f0b1291-c7f3-43c6-bb2e-9f3efb2dc98e","event":"cache_lookup","stage":"cache","cache_status":"miss"}
{"timestamp":"2026-10-21T12:00:01+00:00","level":"INFO","app_env":"prod","request_id":"6f0b1291-c7f3-43c6-bb2e-9f3efb2dc98e","event":"llm_retry","stage":"llm","attempt":1,"next_attempt":2,"retry_in_seconds":0.4,"error_type":"LLMRateLimitError"}
{"timestamp":"2026-10-21T12:00:02+00:00","level":"INFO","app_env":"prod","request_id":"6f0b1291-c7f3-43c6-bb2e-9f3efb2dc98e","event":"pipeline_finished","stage":"pipeline","duration_ms":850.2,"result_status":"success"}
~~~

Middleware принимает X-Request-ID только как корректный UUID, иначе создаёт
новый. Контекст хранится в ContextVar и изолирован между конкурентными запросами.
X-Request-ID добавляется в обычные HTTP-ответы, включая валидационные ошибки.
При необработанной ошибке лог request_finished содержит request_id и HTTP 500;
внешний обработчик Starlette может сформировать сам ответ 500 вне middleware.
Сырой пользовательский X-Request-ID никогда не логируется.

Этапы pipeline: cache, prompt, llm, postprocessing; есть итоговая длительность
pipeline и HTTP-запроса. Cache hit/miss фиксируются сервисом; expired — кешем.
За expired следует miss сервиса. Логи retry создаются Tenacity before_sleep
только для реально запланированных повторов, без логирования последней
исчерпанной попытки как нового retry.

## Проверки

~~~powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
~~~

Тесты проверяют dev/prod, .env, приоритет окружения, совместимый alias ключа,
маскирование Settings, валидацию URL, изоляцию request_id, метрики этапов,
cache hit/miss/expired, retry и отсутствие секретов в JSON-логах.
Ни один unit-тест не обращается к настоящему GigaChat.
