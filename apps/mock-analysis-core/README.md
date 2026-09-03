# Mock Analysis Core

Drop-in CLI-заглушка Analysis Core. Она реализует тот же процессный интерфейс, что
реальное ядро Михаила, но не вызывает модель и не содержит промптов или таксономию.

После корневого `npm run setup` доступны две одинаковые команды: `docreview` и
`docreview-mock`.

```powershell
docreview version

docreview analyze `
  --file "document.pdf" `
  --pack "review-packs/default" `
  --model-config "model-config.yaml" `
  --run-id "review-123" `
  --output "result.json" `
  --artifacts-dir "artifacts" `
  --include-rejected
```

`stdout` содержит только UTF-8 JSON. Диагностика пишется в `stderr`. При наличии
`--output` JSON сначала записывается во временный файл рядом с целевым, затем
атомарно заменяет целевой файл.

Без активного mock-профиля анализ возвращает минимальный валидный результат без
замечаний.

## Success fixtures

В `fixtures/success` находятся три детерминированных сценария:

- `empty.json` — корректный результат без замечаний;
- `standard-12.json` — типовой объём из 12 замечаний;
- `maximum-20.json` — граничный бюджет из 20 замечаний.

Fixtures регенерируются без обращения к модели:

```powershell
..\api\.venv\Scripts\python tools\generate_success_fixtures.py
```

Тесты проверяют совпадение JSON с генератором и общий контракт `ReviewResult`.

## Failure fixtures

`fixtures/failure/manifest.json` связывает имя сценария с exit code, `stderr`,
задержкой и файлом результата. Доступны сценарии ошибки парсинга, неизвестного
Review Pack, недоступной модели, невалидного JSON, несовместимой `schema_version`,
timeout, аварийного завершения и отсутствующего результата после exit code 0.

Структурированные ошибки проходят общий контракт. Невалидный JSON, версия 2.0 и
два сценария без результата намеренно не проходят обычный success path.

Регенерация:

```powershell
..\api\.venv\Scripts\python tools\generate_failure_fixtures.py
```

## Выбор сценария

Сценарии включаются только явным безопасным профилем `test` или `demo`. Настройки
принадлежат mock-executable и не требуют специальных веток в backend:

```powershell
$env:DOCREVIEW_MOCK_PROFILE = "demo"
docreview analyze --file "document.pdf" --pack "review-packs/default" --run-id "demo-1"
```

Профиль `demo` по умолчанию выбирает `standard-12` и ждёт ровно 1200 мс, чтобы UI
успел показать состояние анализа. Профиль `test` выбирает `empty` без задержки.
Для отдельного теста значения можно безопасно переопределить:

```powershell
$env:DOCREVIEW_MOCK_PROFILE = "test"
$env:DOCREVIEW_MOCK_SCENARIO = "model-unavailable"
$env:DOCREVIEW_MOCK_DELAY_MS = "250"
```

Допустимая задержка — от 0 до 30000 мс. Override сценария или задержки без профиля,
а также любой профиль кроме `test`/`demo`, завершается с exit code 2. Поэтому
production-конфигурация не может случайно включить тестовый сценарий.

Доступные success-сценарии: `empty`, `standard-12`, `maximum-20`. Имена всех
failure-сценариев перечислены в `fixtures/failure/manifest.json`. Mock подставляет
актуальные `run_id`, имя и SHA-256 документа, а также ID Review Pack в выбранную
fixture; интерфейс вызова остаётся идентичным реальному Analysis Core.

## Контрактные тесты

`tests/test_cli_contract.py` запускает установленный executable отдельным процессом.
Набор покрывает все предусмотренные exit codes `0`, `2`–`8`, разделение `stdout` и
`stderr`, валидацию JSON Schema, побайтово эквивалентную запись через `--output`,
UTF-8 и сохранение переданного `run_id`. Намеренно повреждённые результаты также
проверяются как отрицательные случаи, а каждый успешный результат ограничен 20
замечаниями.
