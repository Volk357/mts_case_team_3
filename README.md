# DocReview Platform

Платформа для автоматической проверки больших технических документов по правилам
конкретной компании. Product Application принимает документ, запускает независимый
Analysis Core и показывает найденные замечания, не переписывая исходный текст.

## Быстрый старт

Требования: Python 3.11+ и Node.js 22.12+.

```powershell
npm run setup
npm run dev
```

`npm run setup` устанавливает принятое реальное ядро в окружение worker под
командой `docreview`. Тестовый и резервный адаптер остаётся доступен отдельно
как `docreview-mock`.

После запуска доступны:

- frontend — `http://127.0.0.1:5173`;
- Backend API — `http://127.0.0.1:8000`;
- отдельный Review Job worker, читающий durable-очередь из БД;
- Swagger UI — `http://127.0.0.1:8000/api/docs`;
- сквозная диагностика — `http://127.0.0.1:5173/debug/health`.

Остановка всех трёх процессов выполняется через `Ctrl+C`.

## Единая проверка

```powershell
npm run check
```

Команда проверяет Python-контракты, backend lint/format/typecheck/tests с покрытием,
актуальность сгенерированных TypeScript-типов, frontend lint/typecheck/tests и
production build. Эту же последовательность выполняет CI.

## Структура

```text
apps/api/       FastAPI: HTTP API, сервисы, хранилища и workers
apps/web/       React: пользовательский интерфейс и API client
apps/mock-analysis-core/  CLI-совместимая заглушка Analysis Core
contracts/      JSON Schema, fixtures и сгенерированные TypeScript-типы
roadmaps/       декомпозиция работ Никиты
scripts/        единые setup/dev/check команды
tests/          тесты межкомпонентного JSON-контракта
```

Analysis Core остаётся отдельным CLI-модулем Михаила и интегрируется только через
зафиксированный [контракт](INTEGRATION_CONTRACT.md). Промпты и таксономия не должны
переноситься в frontend или Product Application backend.

Рабочий контур Михаила находится в корне репозитория: `run_review.py`,
`check_formal.py`, `score.py`, `generate.py`, YAML-файлы знаний и синтетический
корпус `data/synth`. Его устройство и текущие результаты описаны в
[документации Analysis Core](docs/analysis-core.md).

## Воспроизводимость замеров

Числа полноты и точности в материалах проекта сняты на конкретной сборке
локальной модели. Слой правил воспроизводится кодом и от модели не зависит;
слой модели — зависит, поэтому сборка зафиксирована поимённо:

| Параметр | Значение |
|---|---|
| Модель | `qwen3:30b-a3b`, квантование `Q4_K_M`, 30.5B |
| SHA-256 сборки | `ad815644918f0eaab341c12b67837cc6dd4562342cdaf118f83d5d554cb37226` |
| Контекст | `num_ctx = 32768` |
| Температура | `0` |
| Runtime | Ollama, RTX 4090 |

Как сверить свою копию и почему параметры именно такие — в
[документации локальной модели](docs/local-model.md). Другой `digest` означает
другую сборку, и заявленные числа к ней не относятся.

## Конфигурация

Backend-профили находятся в `apps/api/config`, frontend-профили — в `apps/web`.
Локальные секреты размещаются только в игнорируемых `.env`/`.env.local`. Runtime-файлы
сохраняются в игнорируемом каталоге `data/`.

Подробности:

- [Промежуточная сдача 4 сентября](submission/interim-2026-09-04/README.md);
- [Backend](apps/api/README.md);
- [Frontend](apps/web/README.md);
- [Контракты](contracts/README.md);
- [Покрытие приоритетных областей кейса](docs/case-focus-coverage.md);
- [Сценарий демонстрации и замеренный тайминг](docs/demo-runbook.md);
- [Локальная модель](docs/local-model.md);
- [Приём поставки Analysis Core](docs/analysis-core-acceptance.md);
- [Smoke-проверка реального Analysis Core CLI](docs/real-core-cli-smoke.md);
- [Модель данных приложения](docs/application-data-model.md);
- [Политика хранения и tenant-scoped удаления](docs/storage-retention-policy.md);
- [Roadmaps](roadmaps/README.md).

## Типичный цикл разработки

1. Выполнить `npm run setup` после изменения lock-файлов.
2. Запустить приложение через `npm run dev`.
3. Перед передачей изменений выполнить `npm run check`.
4. При изменении JSON Schema выполнить `npm --prefix contracts run generate:types`.

Lock-файлы Python и npm коммитятся. Сгенерированный
`contracts/generated/review-result.d.ts` также коммитится и проверяется на
рассинхронизацию со схемой.
