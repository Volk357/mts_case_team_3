# Запуск DocReview через Docker Compose

Эта инструкция поднимает готовое приложение вместе с PostgreSQL, миграциями,
API, worker и frontend. Для первого знакомства используйте профиль `mock`: он
воспроизводит полный пользовательский сценарий и не требует VPN или LLM.

## Что понадобится

- Docker Desktop с Compose v2;
- свободный локальный порт `8080`;
- для профиля `real` — доступный Ollama endpoint и загруженная модель.

Все команды выполняются из корня репозитория.

## Первый запуск: mock

1. Создайте локальный файл настроек:

   ```powershell
   Copy-Item .env.example .env
   ```

2. Откройте `.env` и задайте непустой случайный пароль в
   `DOCREVIEW_POSTGRES_PASSWORD`. Например, значение можно получить так:

   ```powershell
   [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(24))
   ```

   Файлы `.env` и `model-config.yaml` исключены из Git. Не добавляйте в них
   публичные или общие демонстрационные пароли.

3. Соберите и поднимите приложение одной основной командой:

   ```powershell
   docker compose --profile mock up --build --wait
   ```

После успешного запуска откройте `http://127.0.0.1:8080`. Загрузите `.docx`,
запустите проверку и дождитесь экрана результатов. Mock worker вернёт
детерминированный набор из 12 замечаний; внешний model endpoint не используется.

## Управление приложением

Показать состояние контейнеров:

```powershell
docker compose --profile mock ps -a
```

Смотреть общие логи:

```powershell
docker compose --profile mock logs --follow --tail 100
```

Смотреть только API и worker:

```powershell
docker compose --profile mock logs --follow --tail 100 api worker-mock
```

Остановить приложение, сохранив базу, документы и результаты:

```powershell
docker compose --profile mock down
```

Повторный `up` использует сохранённые named volumes. Команда ниже удаляет и
контейнеры, и все локальные данные приложения; используйте её только для
осознанного полного сброса:

```powershell
docker compose --profile mock down --volumes
```

## Проверка состояния

После запуска доступны:

- приложение: `http://127.0.0.1:8080`;
- frontend health: `http://127.0.0.1:8080/healthz`;
- общий health API: `http://127.0.0.1:8080/api/health`;
- Swagger UI: `http://127.0.0.1:8080/api/docs`.

Проверить оба health endpoint из PowerShell:

```powershell
Invoke-RestMethod http://127.0.0.1:8080/healthz
Invoke-RestMethod http://127.0.0.1:8080/api/health
```

Frontend должен ответить `ok`. API возвращает JSON со статусами базы и worker;
в рабочем состоянии итоговый `status` равен `ok`.

## Миграции и demo-данные

При обычном `up` миграции применяются автоматически до старта API и worker.
Одноразовый контейнер `migrate` после успеха имеет состояние `Exited (0)` — это
штатное поведение, а не ошибка.

Применить актуальные миграции отдельно:

```powershell
docker compose run --rm migrate
```

Повторно создать только отсутствующие demo-записи:

```powershell
docker compose --profile demo run --rm seed-demo
```

## Запуск с реальной моделью

Профиль `real` заменяет mock worker настоящим Analysis Core. Сначала создайте
локальный конфиг из безопасного примера:

```powershell
Copy-Item review-packs/mts-net/0.2/model-config.example.yaml model-config.yaml
```

В `model-config.yaml` укажите:

```yaml
base_url: http://<доступный-host>:11434/api/chat
model: qwen3:30b-a3b
num_ctx: 32768
timeout: 900
```

Для Ollama на том же компьютере вместо `localhost` используйте
`host.docker.internal`. Для удалённой модели через WireGuard укажите её VPN-IP.
Endpoint должен оканчиваться на нативный путь Ollama `/api/chat`, а не на
`/v1/chat/completions`: этот путь ожидает Analysis Core.

До запуска всего приложения отдельно проверьте связь, наличие модели и пробный
ответ:

```powershell
docker compose --profile real run --rm model-preflight
```

Если preflight завершился успешно, запустите реальный профиль:

```powershell
docker compose --profile real up --build --wait
```

Логи реального анализа:

```powershell
docker compose --profile real logs --follow --tail 100 worker model-preflight
```

Остановить реальный профиль:

```powershell
docker compose --profile real down
```

## Переключение mock и real

Не запускайте `mock` и `real` одновременно: два worker будут конкурировать за
одну очередь. Сначала остановите текущий профиль, затем поднимите другой:

```powershell
docker compose --profile mock down
docker compose --profile real up --build --wait
```

Для обратного переключения поменяйте профили местами. PostgreSQL и остальные
named volumes сохранят документы, задания и результаты между запусками.

## Сборка и диагностика

Проверить Compose-конфигурацию без запуска:

```powershell
docker compose --profile mock config --quiet
```

Полностью пересобрать образы без локального build cache:

```powershell
docker compose --profile mock build --no-cache
```

Типичные причины сбоя:

| Симптом | Что проверить |
|---|---|
| Compose требует `DOCREVIEW_POSTGRES_PASSWORD` | `.env` создан, пароль после `=` не пустой |
| Порт `8080` занят | Задать другой `DOCREVIEW_HTTP_PORT` в `.env` |
| `model-preflight` не видит endpoint | VPN активен, адрес доступен с Docker-хоста, путь заканчивается на `/api/chat` |
| Модель не найдена | Значение `model` совпадает с именем из Ollama `/api/tags` |
| API сообщает о worker как `degraded` | Проверить логи `worker-mock` или `worker` и дождаться его heartbeat |
| `storage-check` завершился с ошибкой | Проверить Docker volumes и доступность каталога `review-packs` |

При неизвестной ошибке сначала сохраните вывод этих двух команд:

```powershell
docker compose --profile mock ps -a
docker compose --profile mock logs --tail 200
```
