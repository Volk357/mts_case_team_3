# DocReview Web

React-приложение продуктового контура DocReview. Оно загружает данные через Backend API и не содержит промптов или логики анализа документов.

## Установка и запуск

```powershell
cd apps/web
npm install
npm run dev
```

Vite запускается на `http://127.0.0.1:5173` и проксирует `/api` на backend `http://127.0.0.1:8000`.

## Конфигурация

Vite автоматически выбирает `.env.development`, `.env.test` или `.env.demo` по
режиму запуска. Локальные переопределения помещаются в игнорируемые Git файлы
`.env.local` или `.env.<mode>.local`.

- `VITE_APP_ENV` — имя окружения;
- `VITE_API_BASE_URL` — origin внешнего API или пустая строка для same-origin;
- `VITE_MAX_UPLOAD_SIZE_BYTES` — клиентский лимит выбора файла, по умолчанию 50 MiB;
- `VITE_DEV_API_PROXY_TARGET` — адрес backend для локального Vite proxy.

Переменные `VITE_*` попадают в браузерный bundle, поэтому секреты в них хранить нельзя.

## Проверки

```powershell
npm run lint
npm run typecheck
npm run test
npm run build
```

Типы результата анализа генерируются из корневой JSON Schema:

```powershell
npm run contracts:generate
npm run contracts:check
```

Frontend импортирует `ReviewResult`, `Finding` и связанные типы только через
`src/api/contracts.ts`. Ручное объявление типа `Finding` блокируется ESLint.

Маршруты текущего каркаса:

- `/` — стартовая страница и загрузка PDF/DOCX с drag-and-drop и прогрессом;
- `/debug/health` — проверка доступности Backend API.

Клиентская проверка формата и размера нужна для быстрого сообщения пользователю;
окончательное решение всегда принимает backend. Загрузка выполняется через
`XMLHttpRequest`, поскольку он предоставляет достоверные события прогресса отправки.
