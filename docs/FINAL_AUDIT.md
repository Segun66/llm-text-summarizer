# Независимый итоговый аудит

Дата: 21 октября 2026 года. Проверяемый репозиторий:
`D:\gitLab\learn\llm-text-summarizer`, ветка `feature/llm-summarizer`,
базовый HEAD `39cfe1a57cadf9ef6913a72bb1579dcd0bc4dca8` и текущие локальные изменения.
Каталог `llm-text-summarize` не является проверяемой Git-копией.

## A. Матрица требований

| Требование | Статус | Фактическое основание |
| --- | --- | --- |
| 1. API / Service / LLM / Postprocessing | Выполнено | DI и Protocol, отдельные prompts, postprocessing, cache; [архитектура](ARCHITECTURE.md) |
| 2. Контракт API и Pydantic | Выполнено | trim 1–10000; strict max_length 50–1000; 200/422/502/503; schema 503 исправлена и проверена |
| 3. GigaChat / OAuth | Выполнено | Протокол проверен документацией и моками; владелец подтвердил реальную генерацию GigaChat-3-Ultra через CLI. HTTP с реальным LLM проверяется отдельно |
| 4. Timeout / retry / jitter | Выполнено | Tenacity, 1–3 попытки; timeout/network/429/5xx; OAuth и генерация имеют отдельные бюджеты |
| 5. Fallback / HTTP | Выполнено | После временных ошибок 503, status=fallback, cached=false; fallback не считается генерацией |
| 6. Исключения | Выполнено | Постоянные ошибки не повторяются; программные ошибки/отмена не превращаются в fallback |
| 7. Кеш | Выполнено | SHA-256: нормализованный текст/max_length/model/prompt version; monotonic TTL, LRU, Lock; тесты hit/miss/expiry |
| 8. Безопасность | Выполнено в проверенной области | TLS включён, redirect запрещён, логи используют allowlist; .env/ключи не отслеживаются; сигнатуры секретов не найдены |
| 9. Конфигурация dev/prod | Выполнено | pydantic-settings, SecretStr, диапазоны и HTTPS URL; .env.example без рабочего ключа; APP_ENV не меняет файл автоматически |
| 10. Unit / API тесты | Выполнено | Последний запуск: 259 passed, 0 skipped, 0 failed, 0 errors; сеть httpx блокируется, MockTransport/TestClient |
| 11. Ruff / установка | Выполнено | Ruff check/format, pip check, сборка/установка wheel, импорт установленного main.app |
| 12. GitHub Actions | Частично | Опубликованный HEAD успешно проверен на Python 3.11; локальные исправления ещё не опубликованы и CI для них не запускался |
| 13. README / TESTING / ARCHITECTURE | Выполнено | Изучены и уточнены текущие результаты, хранение в кеше и состояние GitHub |
| 14. PR и чек-лист | Частично | [Описание PR](PULL_REQUEST.md) готово; удалённых PR нет, default branch пока feature/llm-summarizer |
| 15. Итоговая демонстрация | Не выполнено | План есть в TESTING.md; скриншоты/видео настоящей генерации и cache hit не найдены |

GitHub Actions принят вместо GitLab CI по явному уточнению владельца.
Статус безопасности ограничен проверенными кодом, тестами и сигнатурами;
он не означает сертификацию production-защиты или доказательство отсутствия
секрета любого возможного формата.

## B. Проблемы и приоритеты

Blocker в проверенных локальных сценариях не обнаружен.

| Приоритет | Проблема | Состояние / действие |
| --- | --- | --- |
| major, закрыто для CLI | Реальная интеграция не была проверена при исходном аудите | Владелец подтвердил успешные OAuth и генерацию GigaChat-3-Ultra; HTTP /summarize с реальным LLM и общее качество ещё не проверены |
| major | Нет PR в main и проверки CI для итогового набора изменений | main существует на 39cfe1a; нужен подтверждённый push и PR, затем новый CI |
| major | Отсутствуют готовые скриншоты/видео демонстрации | Снять health, success, 422, fallback, cache hit и CI без секретов |
| minor | OpenAPI не описывал ErrorResponse для защитного 503 из dependency | Исправлено; регрессионный тест сначала упал, после исправления проходит |
| minor | ARCHITECTURE утверждал, что ответы не сохраняются, хотя summary хранится в TTL-кеше | Исправлено: уточнены память/TTL и отсутствие записи на диск |
| minor | CI.md и PR-документ содержали устаревшие сведения о публикации/main | Исправлено по GitHub API; main уже существует, default branch пока feature |
| minor | StarletteDeprecationWarning: TestClient использует httpx | Предупреждение сохранено; все тесты проходят, зависимости ради подавления не расширялись |
| minor | Версии зависимостей ограничены диапазонами без lock-файла | Точная воспроизводимость не гарантируется; это ограничение, не ошибка текущей установки |

## C. Исправления

- В [routes.py](../app/api/routes.py) схема 503 теперь допускает
  SummarizeResponse или ErrorResponse. Исполнение endpoint, HTTP-статусы
  и бизнес-логика не менялись.
- Добавлен [test_audit_regressions.py](../tests/test_audit_regressions.py):
  шесть параметризованных случаев. Проверяются защитные ответы dependency
  503/502 и их OpenAPI, а также 302/404 от OAuth и completion без retry/redirect.
- Уточнены ARCHITECTURE.md, CI.md, README.md, TESTING.md, TEST_COVERAGE.md
  и PULL_REQUEST.md; добавлен этот отчёт.
- Существовавшие до аудита изменения README, TESTING и PR-документа сохранены.
  Реальный .env и пользовательские секреты не читались и не менялись.
- Новые runtime/dev-зависимости в pyproject.toml не добавлены.
  coverage установлен только в игнорируемое временное окружение аудита.

## D. Реальные проверки

Локально: Windows, Python 3.14.7, отдельное окружение
`.venv/ci-validation`. Опубликованный CI проверяет Ubuntu/Python 3.11.
Локального интерпретатора Python 3.11 в этой проверке не запускали.

| Проверка | Результат |
| --- | --- |
| Исходный набор: coverage run --branch --source=app,main -m pytest -q | 248 passed, одно предупреждение, 3.68 с |
| Новые тесты до исправления схемы | 1 failed, 5 passed: подтверждено расхождение OpenAPI 503 |
| Полный набор после исправления | 254 passed, 0 skipped, 0 failed, 0 errors; одно предупреждение; 3.64 с |
| coverage report -m после исправления | 445 statements, 0 missed; 86 branches, 0 partial; 100% |
| ruff check . | All checks passed! |
| ruff format --check . | 44 files already formatted |
| pip check | No broken requirements found |
| pip wheel --no-deps --wheel-dir .venv/audit-dist . | Wheel 0.1.0 успешно собран |
| Установка wheel с --force-reinstall --no-deps | Успешно в окружение аудита с установленными зависимостями |
| python -I: импорт main.app | Успешно из site-packages, без исходников и без рабочего ключа |
| Uvicorn + curl.exe: GET /health | 200, {"status":"ok"} |
| Uvicorn + curl.exe: GET /openapi.json | 200 |
| Uvicorn + curl.exe: пробелы и max_length=49 | 422 в обоих случаях |
| Uvicorn + curl.exe: два запроса к закрытому локальному upstream | Оба 503/fallback/cached=false; точный UTF-8 summary проверен |
| .gitignore через git check-ignore --no-index | .env, .env.prod/.local, .venv, кеши, .key/.pem исключены; .env.example доступен |
| Публикуемые файлы и 40 blob-объектов локальной Git-истории | Нет сигнатур JWT, GitHub token, private key, длинных литералов credentials; запрещённых tracked-файлов нет |
| GitHub API | main и feature на 39cfe1a, PR нет; репозиторий public, default=feature/llm-summarizer |
| Удалённый CI | [39624255439: completed/success](https://github.com/Segun66/llm-text-summarizer/actions/runs/39624255439), SHA 39cfe1a |

Измерено покрытие пакета app и main, а не scripts, тестов или внешних зависимостей.
100% строк и ветвей не доказывают качество модели и корректность на всех входах.
JUnit и временные артефакты находятся в игнорируемом .venv, не включаются в Git.

Версии окружения: FastAPI 0.157.0, Pydantic 2.14.1,
pydantic-settings 2.16.1, httpx 0.28.1, Tenacity 9.2.1,
Uvicorn 0.54.0, pytest 9.1.1, Ruff 0.17.1.

Обычные команды для повторения после установки `python -m pip install -e ".[dev]"`:

~~~bash
python -m pip check
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python -m uvicorn main:app
~~~

Измерение покрытия необязательно и требует отдельной установки coverage.
Зависимости проекта ради измерения не расширялись.

### Сверка GigaChat

Официальные источники проверены 21 октября 2026 года:

- [Авторизация / URL](https://developers.sber.ru/docs/ru/gigachat/api/reference/rest/gigachat-api).
- [Генерация](https://developers.sber.ru/docs/ru/gigachat/api/reference/rest/post-chat).
- [Официальная OpenAPI-схема](https://developers.sber.ru/docs/files/openapi/gigachat/api.yml).

Используются OAuth POST /api/v2/oauth с Basic, form scope и UUID4 RqUID;
генерация POST https://api.giga.chat/v1/chat/completions с Bearer и messages.
OpenAPI задаёт expires_at в миллисекундах; клиент учитывает это.
На HTML-странице авторизации встречается пример с коротким expires_at;
для единиц времени проверена явная спецификация OpenAPI.
Рабочий GigaChat не вызывался.

### Проверка CI

YAML и команды сопоставлены с текущим pyproject и выполнены локально
(установка, импорт, Ruff, pytest). Тот же опубликованный workflow успешно
разобран и выполнен GitHub для SHA 39cfe1a: checkout/setup-python,
Python 3.11, pip cache, push main/feature/** и pull_request main,
15 минут, contents:read, без GigaChat Secrets и continue-on-error.
Актуальные локальные исправления ещё не включены в этот запуск.

## E. Что проверить вручную перед сдачей

1. В локальном терминале выполнить `python -m scripts.check_gigachat`.
   Credentials вводятся скрыто; проверить действительный success, модель/scope,
   квоту, TLS и смысл результата. Проверка может расходовать квоту.
2. Запустить FastAPI с настоящей конфигурацией. Получить 200/success/cached=false,
   затем такой же запрос до TTL → cached=true. Не считать fallback генерацией.
3. По плану [TESTING.md](../TESTING.md) сохранить безопасные демонстрационные
   материалы: health, success, 422, offline fallback, cache hit и успешный CI.
4. Проверить diff и согласовать commit/push. Настроить main как default branch,
   если это требуется условиями сдачи; сама ветка main уже существует.
5. Создать PR feature/llm-summarizer → main только после подтверждения владельца.
   Основа описания — PULL_REQUEST.md; оценивать фактический diff:
   код сервиса уже присутствует в общей базе 39cfe1a.
6. После публикации открыть Actions и Checks PR, сверить новый SHA и все шаги.
   Старый успешный запуск не подтверждает новый коммит.
7. Поставить галочки real GigaChat / demo / новый CI / PR только после проверки.
   Точного внешнего регламента аттестации сверх требований переписки нет.

## F. Вердикт

**Требует доработки перед окончательной сдачей.** Локальная реализация,
установка и автоматические проверки работоспособны; выявленная ошибка
схемы API исправлена. Владелец подтвердил реальную интеграцию через CLI. Остались HTTP /summarize
с настоящим LLM и cache hit, демонстрационные материалы, PR и проверка итоговых
изменений удалённым CI.
Это оставшиеся проверки и оформление сдачи, а не обнаруженная неработоспособность
основного pipeline. Commit, push, создание PR и изменение настроек GitHub
в ходе аудита не выполнялись.

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
