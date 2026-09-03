# DocReview API

Product Application backend. Этот сервис управляет HTTP API и жизненным циклом проверки, но не содержит логику анализа документов, таксономию или промпты.

## Локальная установка

```powershell
cd apps/api
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.lock
.venv\Scripts\python -m pip install --no-deps --no-build-isolation -e .
```

## Запуск

```powershell
.venv\Scripts\python -m uvicorn docreview_api.main:app --reload
```

Проверка:

```text
GET http://127.0.0.1:8000/api/health
```

## Quality gate

```powershell
.venv\Scripts\python -m ruff check src tests
.venv\Scripts\python -m ruff format --check src tests
.venv\Scripts\python -m mypy
.venv\Scripts\python -m pytest --cov
```

## Обновление lock-файла

`requirements.lock` генерируется из `requirements-dev.in` с помощью `pip-tools`:

```powershell
.venv\Scripts\python -m pip install pip-tools
.venv\Scripts\pip-compile requirements-dev.in --output-file requirements.lock --strip-extras --allow-unsafe
```

## Конфигурация

Настройки читаются из переменных окружения с префиксом `DOCREVIEW_`.

Доступны безопасные профили:

- `config/development.env` — локальная разработка;
- `config/test.env` — изолированные тестовые каталоги, CORS отключён;
- `config/demo.env` — демонстрационная сборка.

Для `production` файл профиля намеренно не хранится: настройки и секреты передаются
средой развёртывания.

Профиль выбирается переменной `DOCREVIEW_ENVIRONMENT`. Локальный `apps/api/.env`
загружается после профиля и переопределяет его. Для создания файла скопируйте
`.env.example`; реальные ключи, токены и пароли в Git не добавляются.

Относительные пути `DOCREVIEW_DOCUMENTS_DIR`, `DOCREVIEW_RUNS_DIR` и
`DOCREVIEW_ARTIFACTS_DIR` вычисляются от корня репозитория независимо от текущей
рабочей директории. Все runtime-данные находятся в `data/`, который исключён из Git.

`DOCREVIEW_CORS_ORIGINS` задаётся JSON-массивом точных HTTP(S) origins. Wildcard `*`
не принимается.
