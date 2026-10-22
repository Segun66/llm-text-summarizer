# План проверки LLM Text Summarizer

Документ предназначен для итоговой аттестации.
Команды выполняются из корня репозитория с активированной .venv
после установки python -m pip install -e ".[dev]".
Без активации используйте .\.venv\Scripts\python.exe в PowerShell
или .venv/bin/python в Linux/macOS вместо python.

## 1. Полная автоматическая проверка без ключа

~~~bash
python -m pip check
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
~~~

Настоящий .env не нужен. Тесты передают фиктивные настройки,
мокируют транспорт GigaChat и блокируют стандартные реальные httpx-вызовы.
Retry sleep отключён, TTL управляется fake clock, поэтому ждать 300 секунд не нужно.
Результаты нельзя подменять ожидаемыми: при проверке учитывайте реальный
exit code команды и сводку pytest.

## 2. Успешный запрос

Без обращения к GigaChat:

~~~bash
python -m pytest -q tests/test_http_contract.py -k "valid_text_returns_200_success"
~~~

Тест через FastAPI TestClient запускает lifespan и настоящий pipeline с
подменённым HTTP-транспортом. Ожидание: 200, непустой summary, status=success,
cached=false, длина не более max_length, нормализованные пробелы и пустые строки.

Для ручной проверки настоящей генерации заполните .env и запустите:

~~~bash
python -m uvicorn main:app --reload
~~~

В другом терминале (bash/zsh):

~~~bash
curl -i http://127.0.0.1:8000/summarize -H "Content-Type: application/json" -d '{"text":"Компания запустила сервис сокращения статей. Он выделяет основные факты.","max_length":100}'
~~~

Для PowerShell используйте curl.exe с UTF-8 файлом, как в [README](README.md#12-примеры-curl).
Ожидание при доступном провайдере: 200, status=success, cached=false.
Содержание генерируется моделью и заранее не фиксировано.
503/fallback не считается успешной генерацией.

Отдельная проверка адаптера с безопасным вводом настоящего ключа:

~~~bash
python -m scripts.check_gigachat
~~~

Ключ вводится скрыто, без аргумента командной строки. Успех — сообщение
GigaChat integration OK. и exit code 0. Вызов реальный, может расходовать квоту.
Во время подготовки документации такие вызовы не выполнялись.

## 3. Ошибка валидации

~~~bash
python -m pytest -q tests/test_http_contract.py -k "input_validation"
~~~

Проверяются пустой текст, пробелы/Unicode whitespace, отсутствие text,
10001 символ и неверные max_length (49, 1001, 0, -1, строка, float, bool, null).
Ожидание: HTTP 422, detail — список, ни одного OAuth/LLM-вызова и записи в кеш.

Ручной запрос в bash/zsh:

~~~bash
curl -i http://127.0.0.1:8000/summarize -H "Content-Type: application/json" -d '{"text":"   "}'
~~~

Ожидание: 422. Измените max_length на 49 в валидном запросе — также 422.
Пример точного тела ошибки приведён в README.

## 4. Недоступность GigaChat, retry и fallback

~~~bash
python -m pytest -q tests/test_http_contract.py -k "transient_failures"
python -m pytest -q tests/test_http_contract.py -k "successful_retry"
python -m pytest -q tests/test_http_contract.py -k "authentication_failure"
python -m pytest -q tests/test_http_contract.py -k "invalid_model_response"
~~~

| Сбой | Ожидание |
| --- | --- |
| Timeout, ConnectError, 429, 500 в OAuth или генерации | Не более 3 попыток; при исчерпании HTTP 503/fallback |
| Временная ошибка, затем успех | HTTP 200/success, результат доступен из кеша |
| 401/403 | Одна попытка, HTTP 502/detail, без fallback |
| Пустой/пробельный/null, не-JSON, choices=[], length/blacklist | HTTP 502, без retry и записи в кеш |

Для демонстрации fallback без рабочего ключа запустите отдельный дочерний
процесс на порту 8001. Следующая команда работает после активации .venv;
она переопределяет настройки только дочернего процесса, не меняет .env
или окружение основного терминала и не обращается к GigaChat:

~~~bash
python -c "import os, subprocess, sys; env = os.environ | {'GIGACHAT_CREDENTIALS':'fixture-offline','GIGACHAT_AUTH_URL':'https://127.0.0.1:1/oauth','GIGACHAT_COMPLETIONS_URL':'https://127.0.0.1:1/completion','GIGACHAT_TIMEOUT_SECONDS':'1','GIGACHAT_MAX_ATTEMPTS':'1','NO_PROXY':'127.0.0.1,localhost'}; subprocess.run([sys.executable,'-m','uvicorn','main:app','--port','8001'], env=env, check=True)"
~~~

Порт 1 выбран как обычно закрытый локальный порт. Если он занят вашим сервисом,
используйте другой заведомо недоступный локальный порт.
В другом терминале (bash/zsh):

~~~bash
curl -i http://127.0.0.1:8001/summarize -H "Content-Type: application/json" -d '{"text":"Article for offline check.","max_length":50}'
curl -i http://127.0.0.1:8001/health
~~~

В PowerShell можно передать тело из уникального временного UTF-8 JSON-файла
по примеру README, заменив URL на порт 8001. Health:

~~~powershell
curl.exe -i http://127.0.0.1:8001/health
~~~

Ожидаемый fallback, HTTP 503:

~~~json
{"summary":"Article for offline check.","status":"fallback","cached":false}
~~~

Это исходный текст, а не результат суммаризации. Повторите тот же запрос:
status остаётся fallback и cached остаётся false. Health при этом возвращает
200 и {"status":"ok"}. Остановите демонстрационный сервер через Ctrl+C.

## 5. Cache miss, hit и TTL expiry

~~~bash
python -m pytest -q tests/test_http_contract.py -k "cache_miss_hit_exact_ttl_expiry"
python -m pytest -q tests/test_cache.py
~~~

Сквозной тест проверяет:
1. Первый запрос: HTTP 200/success, cached=false, один вызов генерации.
2. Тот же нормализованный текст в 299.999 секунды: cached=true, нового вызова нет.
3. Ровно в 300 секунд: запись истекает, cached=false, повторная генерация.
4. Логи содержат miss, hit и expired.

Unit-тесты дополнительно проверяют смену text/max_length/модели/версии промпта,
SHA-256 без секретов, LRU, конкурентные запросы и отсутствие кеширования ошибок.
Чтение не продлевает TTL, перезапись обновляет срок.

Вручную с доступной моделью: дважды выполните одинаковый успешный запрос
к одному процессу до истечения TTL. Ожидается false → true.
После перезапуска или expiry снова false. Если получили fallback/503,
попадания не будет: такие результаты не кешируются.

Кеш локален для процесса, поэтому проверяйте один worker.
При reload или смене параметров ключа ожидается промах.

## 6. Проверка логов и health

~~~bash
python -m pytest -q tests/test_http_contract.py -k "no_secret or health_works"
python -m pytest -q tests/test_logging.py
~~~

В логах должны присутствовать UUID request_id, stage, duration_ms, cache_status,
retry attempt и error_type. Не должно быть полного пользовательского текста,
summary, credentials, access_token, Authorization, URL query и текста ошибки провайдера.
Успешный health не доказывает доступность модели и не вызывает бизнес-сервис.

## 7. GitHub Actions

1. Откройте [Actions](https://github.com/Segun66/llm-text-summarizer/actions).
2. Выберите CI и запуск с нужным commit SHA; убедитесь, что это ваша ветка.
3. Проверьте Install dependencies, Build check, Lint и Tests.
4. Успех подтверждается conclusion=success всего запуска, а не только Checkout.
5. Для PR в main проверьте отдельный запуск на вкладке Checks.

Workflow автоматически запускается на push в main/feature/** и pull_request в main.
Python 3.11, pip cache по pyproject.toml, GigaChat Secrets не нужны.
Ошибка установки, импорта, линтера или тестов приводит к failure.
Команды в workflow: python -m pip install ".[dev]", pip check, импорт main.app,
ruff check ., ruff format --check ., pytest -q.

Подтверждённый [успешный запуск для 39cfe1a](https://github.com/Segun66/llm-text-summarizer/actions/runs/39620146660)
проверен через GitHub API при подготовке документов.
Новый commit не наследует этот результат автоматически: его CI нужно проверить отдельно.
Документация в текущей рабочей копии сама по себе не подтверждает новый удалённый запуск.

## 8. Фактические результаты проверки документации

Результаты обновляются только после выполнения команд. На исходном коммите 39cfe1a:
248 passed, 0 skipped, 0 failed; Ruff и удалённый CI успешны.
Локальный Python — 3.14.7, CI — Python 3.11 на Ubuntu.
На том этапе процент покрытия строк/ветвей не измерялся;
актуальное измерение независимого аудита приведено ниже.
Известно одно StarletteDeprecationWarning о TestClient/httpx; предупреждение не скрыто.

Проверено при подготовке README/TESTING.md 21 октября 2026 года:

| Проверка | Фактический результат |
| --- | --- |
| Клонирование feature/llm-summarizer с GitHub | Успешно, в отдельный игнорируемый каталог |
| python -m pip install -e ".[dev]" | Успешно |
| python -m pip check | No broken requirements found |
| python -m pytest -q | 248 passed, 0 skipped, 0 failed; 1 предупреждение Starlette |
| python -m ruff check . | All checks passed |
| python -m ruff format --check . | 42 files already formatted |
| Запуск python -m uvicorn main:app | Успешно, отдельный процесс на свободном localhost-порту |
| curl.exe: health / OpenAPI | HTTP 200 |
| curl.exe: пустой текст / max_length=49 | HTTP 422 |
| curl.exe: два запроса к недоступному локальному провайдеру | HTTP 503/fallback, cached=false оба раза |
| curl.exe: JSON-файл UTF-8 с кириллицей | Передача и валидация HTTP-запроса успешны |
| Локальные Markdown-ссылки и JSON-примеры | Ошибок не найдено |
| CI-бейдж ветки | HTTP 200, passing |
| GitHub CI для 39cfe1a | completed / success, подтверждено API |

Установка и smoke-проверки проводились локально на Windows/Python 3.14.7.
В smoke-запуске использовались фиктивные credentials и закрытый локальный порт,
а не настоящий GigaChat. Примеры реальной генерации выше — ожидаемый контракт,
не фиктивный отчёт об успешном настоящем API-вызове.
Команды bash/zsh приведены по эквивалентной схеме; Linux shell локально
не запускался. Запуск среды Ubuntu/Python 3.11 подтверждён предыдущим GitHub CI.
Документационные изменения README/TESTING.md пока не опубликованы в новом коммите.


## 9. Что предоставить преподавателю

- README и этот план проверки.
- Сводку pytest и результат Ruff из своего запуска.
- Ответы /health, успешного /summarize, валидации, fallback и cache hit.
- Ссылку на успешный CI с точным SHA.
- При ручной генерации не включайте в отчёт .env, ключи и заголовки авторизации.

Полный аудит сценариев: [TEST_COVERAGE.md](docs/TEST_COVERAGE.md).
Проверки реальной квоты/авторизации GigaChat, качества резюме и нагрузочного
поведения выполняются отдельно; моки не подтверждают эти свойства.

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

## Дополнение: диагностика ручного подключения GigaChat

После сообщения пользователя об общем LLMServiceError исправлен ручной CLI:
ожидаемый отказ больше не печатает traceback; выводятся только stage
(oauth/completion) и числовой HTTP-статус. Тело ответа, URL, заголовки,
ключ и токен не выводятся. Программные ошибки по-прежнему распространяются.

Полный повторный запуск: 259 passed, 0 skipped, 0 failed, одно предупреждение
Starlette; Ruff check и format проходят. Добавлено пять тестовых случаев;
существующие проверки 302/404 дополнены проверкой диагностических атрибутов.
Сетевые вызовы в тестах подменены. Причина реального отказа ещё не установлена:
нужно повторить python -m scripts.check_gigachat и получить stage/HTTP-статус.
Предыдущее измерение покрытия относится к состоянию до этого дополнения;
после изменения диагностики покрытие повторно не измерялось.

## Подтверждение реальной интеграции — 21 октября 2026 года

Источник: результат запуска в локальном терминале, предоставленный владельцем
проекта в переписке. Агент самостоятельно настоящий ключ не использовал.

Режим: Freemium; модель: `GigaChat-3-Ultra`. Команда:

~~~powershell
.\.venv\Scripts\python.exe -m scripts.check_gigachat
~~~

Полученный вывод (приглашение ввода ключа опущено):

~~~text
GigaChat integration OK.
Выпущен HTTP API для сокращения текста с валидацией данных и использованием GigaChat.
~~~

Это подтверждает успешную цепочку OAuth → получение токена → генерация
на этой конфигурации и коротком тестовом тексте. В отличие от предыдущих
проверок с моками, здесь выполнен реальный вызов по сообщению владельца.
Предыдущие отметки «реальная интеграция не проверена» относятся к состоянию
до этого результата. Ошибка completion/404 устранена после выбора модели
Freemium вместо исходного значения GigaChat.

Успешный вызов адаптера не является проверкой HTTP /summarize с реальным LLM:
ещё нужно получить 200/success/cached=false, повторить тот же запрос
до истечения TTL и подтвердить cached=true. Числовой остаток квоты,
нагрузочные характеристики и общее качество модели этим smoke-тестом не измерены.
PR, CI итогового коммита и демонстрационные скриншоты остаются отдельными шагами.
