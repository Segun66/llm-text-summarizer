# Аудит тестового покрытия

Аудит выполнен 21 октября 2026 года. Проверены тесты API, сервиса, LLM-адаптера,
кеша, конфигурации, логирования, lifecycle HTTP-клиента и ручного проверочного
скрипта. Добавлен tests/test_http_contract.py: FastAPI TestClient запускает
настоящий lifespan, роуты, сервис, постобработку, кеш и GigaChatClient.
Подменяются только внешнее HTTP-взаимодействие через MockTransport,
monotonic clock и подключение обработчика логов в тестовую StringIO.

Это аудит покрытия сценариев. Процент покрытия строк/ветвей не измерялся:
coverage/pytest-cov не установлены, зависимости проекта не расширялись.
Наличие теста не означает доказательство корректности для любых входных данных.

## Обязательные сценарии

Все имена ниже относятся к [tests/test_http_contract.py](../tests/test_http_contract.py).

| № | Сценарий | Проверка и тест |
| --- | --- | --- |
| 1 | Валидный текст | test_valid_text_returns_200_success: 200, summary, success, cached=false, постобработка и длина |
| 2 | Пустой текст | test_input_validation_rejects_before_any_provider_call[empty]: 422, ноль внешних вызовов |
| 3 | Только пробелы | Тот же тест [spaces] и [unicode-whitespace]: 422 |
| 4 | Слишком длинный текст | Тот же тест [too-long]: 10001 символ → 422 |
| 5 | Неверный max_length | Тот же тест: 49, 1001, 0, -1, строка, float, bool, null → 422 |
| 6 | Timeout | test_transient_failures_retry_then_fallback_never_cached: 3 попытки, 503/fallback, пустой кеш |
| 7 | Network error | Тот же тест: ConnectError, OAuth и генерация проверены отдельно |
| 8 | Авторизация | test_authentication_failure_never_retried_or_cached: 401/403 → одна попытка, 502, без fallback |
| 9 | 429 и 500 | Тест временных ошибок: ровно 3 попытки; test_successful_retry_returns_success_then_cache_hit: успешный retry и кеш |
| 10 | Пустой/некорректный ответ | test_invalid_model_response_is_502_without_retry_or_cache: пустой/пробельный/null, не-JSON, choices=[], length, blacklist |
| 11 | Cache miss/hit/expiry | test_http_cache_miss_hit_exact_ttl_expiry: промах, попадание в 299.999 с, истечение ровно в 300 с |
| 12 | Fallback не кешируется | Два одинаковых запроса снова выполняют по 3 попытки, cached=false и кеш пуст |
| 13 | Секреты не в логах | test_no_secret_or_full_user_text_in_http_retry_logs: credentials, токен, заголовок, URL query, полный текст и тело ошибки отсутствуют |
| 14 | Health без LLM | test_health_works_without_llm_or_business_dependency: 200/ok даже с недоступным провайдером и запрещённым dependency |

Новый файл добавляет 41 параметризованный тестовый случай. До дополнения
в проекте было 207 случаев, после — 248. Существующие тесты сохранены.

## Покрытие остальных слоёв

| Файл | Проверки |
| --- | --- |
| test_api.py | Pydantic-валидация, границы длины после trim, DI, неизвестные поля, malformed JSON, HTTP-маппинг |
| test_service.py | Порядок pipeline, промпты только на промахе, postprocessing перед записью, ошибки/отмена без fallback и кеша |
| test_gigachat.py | Basic/Bearer, scope, payload, UUID4, кеш и истечение токена, JSON, промпты, настройки и безопасные исключения |
| test_llm_errors.py | Типы ошибок, OAuth/генерация, retry/exhaustion, постоянные ошибки, 500 при ошибках программирования |
| test_llm_factory.py | Проверка TLS/hostname, timeout, запрет redirect, закрытие HTTP-клиента при успехе и ошибке |
| test_cache.py | SHA-256 и нормализация, все параметры ключа, TTL, LRU, обновление записи, конкурентность, отсутствие кеширования ошибок |
| test_settings.py | dev/prod, env/.env/init, aliases credentials, SecretStr, некорректные параметры и скрытый input ошибок |
| test_logging.py | JSON allowlist, request_id и конкуренция, длительности, cache/retry, секреты в message/args/extra/exception |
| test_check_gigachat.py | Безопасный ручной CLI, корректный exit code, прямой вызов без fallback |

## Сетевая изоляция и время

В tests/conftest.py autouse-фикстура блокирует стандартные HTTPTransport и
AsyncHTTPTransport: случайный реальный httpx-вызов сразу завершает тест ошибкой.
test_real_network_guard_blocks_default_httpx_transport проверяет эту защиту.
MockTransport, ASGITransport и внутренний транспорт TestClient продолжают работать.
Защита относится к httpx, единственному HTTP-клиенту приложения.

Tenacity использует no-op sleep, реальные задержки не выполняются.
TTL управляется fake clock без sleep. Реальные ключи и локальный .env
не нужны; Settings передаются с _env_file=None и фиктивными credentials.

## Результат запуска

~~~text
248 passed
skipped: 0
failed: 0
errors: 0
~~~

Команды из корня проекта:

~~~powershell
.\.venv\Scripts\python.exe -m pytest -q --junitxml=.venv/pytest-audit.xml
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
~~~

Установленная Starlette выдаёт одно StarletteDeprecationWarning при импорте
FastAPI TestClient: интеграция с httpx помечена устаревшей в пользу httpx2.
Тесты с текущим httpx работают и проходят; предупреждение не скрывается.
Зависимости ради него не менялись.

Вне unit-покрытия остаются настоящая авторизация/квота/сертификаты GigaChat,
качество сгенерированного содержания и нагрузочное поведение в production.
Они требуют отдельных интеграционных и нагрузочных проверок.

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
Полная матрица требований, проблемы и ручные шаги: [FINAL_AUDIT.md](FINAL_AUDIT.md).
