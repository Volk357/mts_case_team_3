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

- `/` — стартовая страница;
- `/debug/health` — проверка доступности Backend API.
