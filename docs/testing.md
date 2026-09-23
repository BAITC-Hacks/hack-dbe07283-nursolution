# Проверки и CI

[README](../README.md) · [Архитектура](architecture.md) · [Каталог](catalog.md)

## Основной набор

62 теста API, фильтрации, ранжирования, объяснений, кеша, таймаутов, метрик и
границ доступа редактора. OpenAI заменён тестовыми клиентами.

```bash
python -m pip install -r requirements-dev.txt
python -m unittest -v
```

В Windows используйте `.\.venv\Scripts\python.exe`, в Linux / macOS — `.venv/bin/python`.
В Docker: `docker compose run --build --rm tests`.

## PostgreSQL

Три интеграционных теста проверяют равенство исходных каталогов, повторную
инициализацию без потери правок, сохранение, конфликт версий и влияние изменения
профиля на новый поиск. Каждый тест создаёт отдельную случайную схему и удаляет
только её после завершения. Пользователь тестовой базы должен иметь право создавать схемы.

Запустите локальную базу: `docker compose --profile postgres up -d --wait db`.

**PowerShell:**

```powershell
$env:POSTGRES_TEST_URL = "postgresql://nur:nur_local_dev@127.0.0.1:55432/nur"
.\.venv\Scripts\python.exe -m unittest discover -s integration -v
```

**Bash:**

```bash
POSTGRES_TEST_URL=postgresql://nur:nur_local_dev@127.0.0.1:55432/nur .venv/bin/python -m unittest discover -s integration -v
```

Если пароль или порт отличаются, измените тестовый URL. Без `POSTGRES_TEST_URL`
интеграционные тесты пропускаются; это не считается проверкой базы.

## Браузерные сценарии

Тесты запускают собственный Uvicorn на свободном локальном порту, в офлайн-режиме
и с пустым ключом OpenAI. Рабочий сервер на 8000/8080 не меняется. Браузер использует
новый изолированный профиль. Скриншоты и серверные логи находятся в `test-results/`.

```bash
python -m pip install -r requirements-e2e.txt
python -m playwright install chromium
python -m unittest discover -s e2e -v
```

На Linux для установки системных библиотек браузера:
`python -m playwright install --with-deps chromium`.

Семь сценариев проверяют главную, переход к форме без автоматического подбора,
перенос выбранной категории, навигацию, стабильный порядок, условия карточки,
пустую выдачу и применение подсказки, отсутствующую категорию, мобильную ширину,
валидацию формы и редактор.
При заданном `POSTGRES_TEST_URL` выполняются ещё семь сценариев с
PostgreSQL, включая добавление и изменение профиля через интерфейс. Без переменной
эти семь проверок будут явно помечены как пропущенные.

Для проверки на установленном Edge можно задать `E2E_BROWSER_CHANNEL=msedge`.
В CI используется Chromium. Локальная проверка текущей реализации выполнена
в Edge на Chromium; загрузка отдельного Chromium на этой машине завершалась таймаутом.

## GitHub Actions

[`checks.yml`](../.github/workflows/checks.yml) запускается на `push`, `pull_request`
и вручную (`workflow_dispatch`). Pipeline содержит:

| Job | Проверки |
| --- | --- |
| `backend` | Основной набор и совместимость зависимостей на Python 3.10 / 3.12 |
| `database-and-browser` | PostgreSQL 16, интеграционные тесты и оба набора браузерных сценариев |
| `docker` | Compose, тестовый образ, runtime-образ, healthcheck, метрики и статические модули |

Доступ workflow ограничен `contents: read`; OpenAI выключен, секреты репозитория
не требуются. Браузерные скриншоты и логи сохраняются как artifact на 7 дней.
Workflow начнёт выполняться после публикации файлов в GitHub, если Actions разрешены
в настройках репозитория. Локальные успешные тесты не означают, что workflow уже прошёл на GitHub.

Использованы официальные инструкции [Playwright CI](https://playwright.dev/python/docs/ci)
и [GitHub Actions для Python](https://docs.github.com/en/actions/tutorials/build-and-test-code/python).
