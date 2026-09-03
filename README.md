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

## Конфигурация

Backend-профили находятся в `apps/api/config`, frontend-профили — в `apps/web`.
Локальные секреты размещаются только в игнорируемых `.env`/`.env.local`. Runtime-файлы
сохраняются в игнорируемом каталоге `data/`.

Подробности:

- [Backend](apps/api/README.md);
- [Frontend](apps/web/README.md);
- [Контракты](contracts/README.md);
- [Локальная модель](docs/local-model.md);
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
