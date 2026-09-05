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

Worker запускается отдельным процессом:

```powershell
.venv\Scripts\python -m docreview_api.workers.review_worker
```

## Backend Docker image

Один образ содержит Backend API, worker, миграции и установленный настоящий
Analysis Core. Сборка выполняется от корня репозитория, поскольку ядро и JSON
Schema находятся вне `apps/api`:

```powershell
docker build --file apps/api/Dockerfile --tag docreview-backend:local .
```

Команда образа по умолчанию запускает API. Worker и миграции используют тот же
образ с другой командой; entrypoint заменяет себя целевым процессом и корректно
передаёт ему сигналы остановки:

```text
API:        api
Worker:     worker
Миграции:   migrate
Demo seed:  seed-demo
```

Для worker задаётся `DOCREVIEW_CONTAINER_ROLE=worker`. Оба процесса работают
от непривилегированного пользователя `docreview` (UID/GID 10001). Настройки
PostgreSQL и путь к смонтированному model config передаются окружением; сам
model config и секреты в образ не копируются.

Healthcheck API вызывает `/api/health` и требует готовности базы и worker.
Healthcheck worker проверяет свежесть файла `DOCREVIEW_WORKER_HEARTBEAT_PATH`.
При запуске двух ролей они должны видеть общий каталог `/app/data`.

## PostgreSQL через Compose

Создайте локальный `.env` из корневого `.env.example` и заполните
`DOCREVIEW_POSTGRES_PASSWORD` длинным случайным URL-safe значением. Пароля по
умолчанию нет: без него Compose завершится до создания контейнера.

```powershell
docker compose up --build postgres migrate
```

PostgreSQL хранит данные в именованном volume `docreview-postgres-data`, проверяет
готовность через `pg_isready`, а `migrate` запускается только после успешного
healthcheck базы. Будущие API и worker будут зависеть от успешного завершения
`migrate`, а не только от открытого порта PostgreSQL.

Миграции не создают демонстрационные записи. Идемпотентный demo seed запускается
отдельно и защищён профилем и явным флагом:

```powershell
docker compose --profile demo run --rm seed-demo
```

Команда откажется работать, если окружение не `demo` или не установлен
`DOCREVIEW_ALLOW_DEMO_SEED=true`.

## Хранилища контейнеров

Compose создаёт отдельные именованные volumes для загруженных документов,
рабочих каталогов Analysis Core, экспортируемых диагностик и heartbeat worker.
Имена можно переопределить переменными `DOCREVIEW_DOCUMENTS_VOLUME`,
`DOCREVIEW_RUNS_VOLUME`, `DOCREVIEW_ARTIFACTS_VOLUME` и
`DOCREVIEW_STATE_VOLUME`. API и worker будут подключать один и тот же набор.

Каталог `review-packs` подключается из репозитория как read-only bind mount:
контейнеры могут читать таксономию и промпты, но не менять исходный Context Pack.
Перед стартом backend-сервисов одноразовый `storage-check` проверяет, что все
рабочие volumes принадлежат непривилегированному пользователю `10001:10001`,
доступны для записи, а Review Packs действительно защищены от записи.

```powershell
docker compose run --rm storage-check
```

Удаление контейнеров не удаляет данные. Полное удаление именованных volumes
выполняется только явной командой `docker compose down --volumes`; она удаляет
загруженные документы и результаты запусков, поэтому для обычной остановки её
использовать не следует.

## Подключение модели из контейнера

Real-профиль получает конфигурацию модели не из образа и не из командной строки,
а через Compose secret. Скопируйте безопасный пример, укажите доступный из
контейнера адрес и не добавляйте получившийся файл в Git:

```powershell
Copy-Item review-packs/mts-net/0.2/model-config.example.yaml model-config.yaml
docker compose --profile real run --rm model-preflight
```

Для Ollama на том же компьютере вместо `localhost` нужен адрес
`host.docker.internal`. Для сервера через WireGuard указывается его туннельный
IP напрямую. Analysis Core использует нативный путь Ollama `/api/chat`; путь
`/v1/chat/completions` для этого runtime не подходит.

`model-preflight` сначала читает `/api/tags`, проверяет наличие точного тега
модели, затем выполняет короткий запрос к `/api/chat` с `think: false` и
настроенным `num_ctx`. Диагностика различает отсутствующий или битый конфиг,
недоступную сеть, HTTP/auth-ошибку, отсутствующую модель и некорректный ответ
inference. В сообщениях не печатаются query-параметры URL или содержимое secret.


Корневой `npm run dev` запускает API, worker и web-приложение вместе. Worker
атомарно забирает старейший `queued` job, поэтому два одновременно запущенных
экземпляра не исполняют одну проверку. После перезапуска он помечает слишком старые
`running` job ошибкой `WORKER_INTERRUPTED`; исходный job не переоткрывается.

Проверка:

```text
GET http://127.0.0.1:8000/api/health
```

Публичные правила prefix, UUID, дат и единого error envelope зафиксированы в
[`docs/api-conventions.md`](../../docs/api-conventions.md). OpenAPI доступен по
`GET /api/openapi.json`, Swagger UI — по `/api/docs`.

Примеры полного HTTP-сценария и каталог публичных ошибок находятся в
[`docs/backend-api.md`](../../docs/backend-api.md). Зафиксированный OpenAPI-контракт —
[`openapi.json`](openapi.json). Обновить его после изменения endpoint или transport schema:

```powershell
cd apps/api
.venv\Scripts\python scripts\generate_openapi.py
.venv\Scripts\pytest tests\test_openapi_snapshot.py
```

## База данных

**PostgreSQL во всех окружениях**, включая локальное и тестовое. SQLite убран
намеренно: приложение пишет в базу из двух процессов (API и воркер), а удаление
документа при живой проверке опирается на блокировку строки и
`SELECT ... FOR UPDATE` — в SQLite их нет, и пришлось бы сериализовать все
транзакции, то есть тестировать одну модель параллелизма, а поставлять другую.
Подключение задаётся через `DOCREVIEW_DATABASE_URL`.

Тесты создают собственную базу на каждый тест, поэтому роли для них нужен
`CREATEDB`; адрес берётся из `DOCREVIEW_TEST_DATABASE_URL`.

Применить миграции:

```powershell
cd apps/api
.venv\Scripts\python -m alembic upgrade head
```

Откатить последнюю миграцию:

```powershell
.venv\Scripts\python -m alembic downgrade -1
```

Schema автоматически не создаётся при импорте приложения: миграции остаются
явной операцией запуска. Repository layer не выполняет скрытые commit; атомарное
завершение review использует отдельную транзакцию `complete_review_job`.

## Quality gate

```powershell
.venv\Scripts\python -m ruff check src tests scripts alembic
.venv\Scripts\python -m ruff format --check src tests scripts alembic
.venv\Scripts\python -m mypy
.venv\Scripts\python -m pytest --cov --basetemp .tmp-pytest-check -p no:cacheprovider
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

Относительные пути `DOCREVIEW_DOCUMENTS_DIR`, `DOCREVIEW_RUNS_DIR`,
`DOCREVIEW_ARTIFACTS_DIR` и `DOCREVIEW_REVIEW_PACKS_DIR` вычисляются от корня
репозитория независимо от текущей рабочей директории. Все runtime-данные находятся
в `data/`, который исключён из Git.

Частота чтения очереди задаётся `DOCREVIEW_WORKER_POLL_INTERVAL_SECONDS`. Значение
`DOCREVIEW_WORKER_STALE_AFTER_SECONDS` обязано превышать сумму общего timeout анализа
и времени мягкой остановки процесса, чтобы новый worker не завершил ещё работающий job.

Реальное ядро выбирается через `DOCREVIEW_ANALYSIS_EXECUTABLE`, а локальный файл
его модели — через `DOCREVIEW_ANALYSIS_MODEL_CONFIG_PATH`. Worker передаёт этот
путь отдельным аргументом `--model-config`; содержимое и секреты файла не читаются
и не журналируются приложением. Development/demo-профили ожидают игнорируемый
`model-config.yaml` в корне репозитория. Для возврата к резервному адаптеру задайте
`DOCREVIEW_ANALYSIS_EXECUTABLE=docreview-mock` и уберите путь к model config.
Для development/demo внешний timeout worker равен 600 секундам: он покрывает
замеренные 65–80 секунд через WireGuard и прогрев модели. После 600 секунд процесс
завершается управляемо, а job получает терминальный статус `timed_out`; окно
восстановления worker установлено в 900 секунд.

`DOCREVIEW_CORS_ORIGINS` задаётся JSON-массивом точных HTTP(S) origins. Wildcard `*`
не принимается.

## Загрузка документов

`POST /api/documents` принимает multipart-поле `document`. Разрешены только `.pdf`
с media type `application/pdf` и `.docx` с Office Open XML media type. Backend
сверяет расширение, заявленный media type и фактическую структуру файла, отклоняет
пустые файлы и имена, содержащие путь. Отображаемое имя нормализуется в Unicode NFC
и никогда не используется как внутреннее имя хранения.

Максимальный размер задаётся `DOCREVIEW_MAX_UPLOAD_SIZE_BYTES`; значение по
умолчанию — `52428800` байт (50 MiB). Файл потоково записывается во временный
объект внутри `DOCREVIEW_DOCUMENTS_DIR`, одновременно вычисляется SHA-256. После
проверки формата временный файл атомарно перемещается под именем из UUID, и только
затем создаётся запись `Document`. При ошибке временный или уже перемещённый файл
удаляется.

До появления авторизации загрузки относятся к системной MVP-компании, заданной
`DOCREVIEW_DEFAULT_COMPANY_ID`, `DOCREVIEW_DEFAULT_COMPANY_SLUG` и
`DOCREVIEW_DEFAULT_COMPANY_NAME`. Внутренний storage key и абсолютный путь для Job
Runner формируются backend и никогда не возвращаются клиенту.

### Защита и эксплуатация загрузок

Временные файлы получают права `0600`, постоянные — `0640`, storage-каталоги —
`0750` (на Windows применяются поддерживаемые ОС эквиваленты). Перед атомарным
перемещением вызывается `AntivirusScanner`. В MVP явно подключён
`DisabledAntivirusScanner`; для production dependency заменяется адаптером ClamAV
или внутреннего антивируса. Отклонённый сканером файл удаляется и не создаёт
`Document`.

Upload-метрики содержат только число успешных загрузок, суммарный размер, число
ошибок и их техническую категорию. Байты документа, исходное имя и storage path в
метрики или логи не записываются.

Очистка orphan-файлов не запускается автоматически. Явная идемпотентная команда:

```powershell
cd apps/api
.venv\Scripts\python -m docreview_api.maintenance.cleanup_uploads
```

Она удаляет только файлы старше
`DOCREVIEW_ORPHAN_UPLOAD_GRACE_PERIOD_HOURS` (24 часа по умолчанию): временные
`upload-*.tmp` и UUID-файлы PDF/DOCX, для которых нет записи `Document`. Symlink,
неизвестные имена и свежие файлы пропускаются; результат содержит только счётчики.
