# Приём поставки Analysis Core

## Зафиксированная поставка

| Компонент | Принятая версия |
|---|---|
| Analysis Core CLI | `docreview-analysis-core 0.2.0` |
| Review Result JSON Schema | `1.0` |
| Review Pack | `mts-net 0.2` |
| Модель | `qwen3:30b-a3b` |

Версия ядра закреплена в `pyproject.toml` и выводится самим CLI. Команда общей
подготовки проекта устанавливает ядро в то же Python-окружение, в котором
работает worker. Исходный код ядра остаётся на границе CLI в корне репозитория
и не импортируется backend-приложением.
Runtime-зависимости ядра закреплены отдельно в `requirements-core.lock`.

## Проверка после установки

```powershell
npm run setup
apps/api/.venv/Scripts/docreview.exe version
apps/api/.venv/Scripts/docreview.exe validate-pack --pack review-packs/mts-net/0.2
```

На Linux имя исполняемого файла — `apps/api/.venv/bin/docreview`. Первая команда
должна вернуть JSON с версиями `0.2.0` и `1.0`, вторая — `status: valid`,
`id: mts-net`, `version: 0.2`. Ненулевой exit code означает, что поставка или
Review Pack не готовы к запуску worker.

Mock не удалён: для тестового и резервного запуска используйте отдельную команду
`docreview-mock`. Переключение выполняется переменной
`DOCREVIEW_ANALYSIS_EXECUTABLE`; frontend и HTTP API при этом не меняются.

## Конфигурация модели и секреты

1. Скопировать `review-packs/mts-net/0.2/model-config.example.yaml` в локальный
   `model-config.yaml` в корне репозитория.
2. Заменить placeholder адресом доступного через WireGuard Ollama endpoint.
3. Не добавлять файл в Git: корневой `model-config.yaml`, `.env` и VPN-профили
   исключены через `.gitignore`.
4. Перед анализом проверить `/api/tags` и наличие точного тега модели. Digest
   принятой сборки и безопасная команда проверки приведены в `docs/local-model.md`.

Файл конфигурации не должен содержать VPN private key, пароль или access token.
Если endpoint всё же требует credential, он передаётся только как локальный
секрет окружения и не выводится в диагностические артефакты.

Параметры принятой конфигурации: `num_ctx: 32768`, `timeout: 900`, модель
`qwen3:30b-a3b`; для структурированного ответа ядро выставляет `think: false`.
