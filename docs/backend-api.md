# Backend API

Документ описывает публичный HTTP-контракт MVP. Базовый адрес локального API —
`http://127.0.0.1:8000`, prefix всех продуктовых endpoint — `/api`. Актуальная
машиночитаемая схема хранится в [`apps/api/openapi.json`](../apps/api/openapi.json),
во время работы приложения доступна по `GET /api/openapi.json`.

## Пользовательский сценарий

### 1. Получить Review Pack

```http
GET /api/review-packs HTTP/1.1
Host: 127.0.0.1:8000
```

```json
{
  "items": [
    {
      "review_pack_id": "11111111-1111-4111-8111-111111111111",
      "display_name": "Техническая спецификация",
      "document_type": "technical_specification",
      "version": "1.0"
    }
  ],
  "total": 1
}
```

Клиент выбирает только опубликованный идентификатор. Путь к пакету никогда не
передаётся и не возвращается.

### 2. Загрузить документ

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/documents `
  -H "X-Correlation-ID: ui-upload-1" `
  -F "document=@requirements.pdf;type=application/pdf"
```

```http
HTTP/1.1 201 Created
X-Correlation-ID: ui-upload-1
Content-Type: application/json
```

```json
{
  "document_id": "22222222-2222-4222-8222-222222222222",
  "filename": "requirements.pdf",
  "size_bytes": 184220,
  "media_type": "application/pdf"
}
```

Поддерживаются PDF и DOCX. В ответе нет SHA-256, storage key или локального пути.

### 3. Создать асинхронную проверку

```http
POST /api/reviews HTTP/1.1
Host: 127.0.0.1:8000
Content-Type: application/json
Idempotency-Key: review-submit-1

{
  "document_id": "22222222-2222-4222-8222-222222222222",
  "review_pack_id": "11111111-1111-4111-8111-111111111111"
}
```

```http
HTTP/1.1 202 Accepted
Location: /api/reviews/33333333-3333-4333-8333-333333333333
Retry-After: 2
```

```json
{
  "review_id": "33333333-3333-4333-8333-333333333333",
  "document_id": "22222222-2222-4222-8222-222222222222",
  "review_pack_id": "11111111-1111-4111-8111-111111111111",
  "status": "queued",
  "stage": "waiting",
  "queued_at": "2026-09-04T06:00:00Z",
  "started_at": null,
  "finished_at": null,
  "poll_after_ms": 2000,
  "error": null
}
```

Повтор с тем же `Idempotency-Key` и тем же телом возвращает тот же review. Тот же
ключ с другим телом возвращает `409 IDEMPOTENCY_CONFLICT`.

### 4. Дождаться результата через polling

Клиент делает `GET` по значению `Location` и использует `poll_after_ms` или
`Retry-After`, не запуская несколько циклов polling для одного review.

```http
GET /api/reviews/33333333-3333-4333-8333-333333333333 HTTP/1.1
Host: 127.0.0.1:8000
```

Для незавершённой проверки возвращается текущее публичное состояние и следующий
интервал. После завершения `poll_after_ms` становится `null`, а `Retry-After`
исчезает:

```json
{
  "review_id": "33333333-3333-4333-8333-333333333333",
  "document_id": "22222222-2222-4222-8222-222222222222",
  "review_pack_id": "11111111-1111-4111-8111-111111111111",
  "status": "completed",
  "stage": "result_ready",
  "queued_at": "2026-09-04T06:00:00Z",
  "started_at": "2026-09-04T06:00:01Z",
  "finished_at": "2026-09-04T06:00:18Z",
  "poll_after_ms": null,
  "error": null
}
```

В API не публикуются имя модели, prompt, PID процесса и диагностические сообщения.

### 5. Получить замечания

```http
GET /api/reviews/33333333-3333-4333-8333-333333333333/findings HTTP/1.1
Host: 127.0.0.1:8000
```

```json
{
  "review_id": "33333333-3333-4333-8333-333333333333",
  "items": [
    {
      "finding_id": "44444444-4444-4444-8444-444444444444",
      "ordinal": 0,
      "defect_id": "AMBIGUOUS_LOGIC",
      "severity": "high",
      "confidence": 0.91,
      "location": {"page": 3, "section_path": ["Логика отбора"], "block_id": "p-18"},
      "quote": "Записи обрабатываются регулярно",
      "problem": "Не указана точная периодичность обработки.",
      "clarification": "Указать интервал или событие запуска обработки."
    }
  ],
  "total": 1
}
```

API указывает место и возможную корректировку, но не переписывает исходный документ.

### 6. Сохранить решение по замечанию

```http
PUT /api/findings/44444444-4444-4444-8444-444444444444/feedback HTTP/1.1
Host: 127.0.0.1:8000
Content-Type: application/json
X-Actor-Key: browser-session-1

{
  "decision": "accepted",
  "comment": "Исправим периодичность"
}
```

```json
{
  "feedback_id": "55555555-5555-4555-8555-555555555555",
  "finding_id": "44444444-4444-4444-8444-444444444444",
  "decision": "accepted",
  "comment": "Исправим периодичность",
  "created_at": "2026-09-04T06:01:00Z",
  "updated_at": "2026-09-04T06:01:00Z"
}
```

Повторный `PUT` изменяет решение того же пользователя, но не изменяет Finding.

## Ошибки и эксплуатационные заголовки

Все ошибки используют одну форму:

```json
{
  "error": {
    "code": "DOCUMENT_NOT_FOUND",
    "message": "Document was not found.",
    "details": []
  }
}
```

Основные коды: `DOCUMENT_NOT_FOUND`, `REVIEW_PACK_NOT_FOUND`, `REVIEW_NOT_FOUND`,
`FINDING_NOT_FOUND`, `IDEMPOTENCY_CONFLICT`, `REQUEST_VALIDATION_ERROR`,
`REQUEST_TOO_LARGE`, `RATE_LIMIT_EXCEEDED` и `INTERNAL_ERROR`. Неизвестные document,
Review Pack, review и finding различаются кодом, но ответ не раскрывает внутренние пути,
секреты или диагностические данные.

Каждый ответ содержит `X-Correlation-ID`. Безопасный идентификатор клиента сохраняется,
иначе API создаёт новый. При ограничении частоты запросов ответ `429` содержит
`Retry-After`, `X-RateLimit-Limit` и `X-RateLimit-Remaining`.

## Проверка контракта

```powershell
cd apps/api
.venv\Scripts\python scripts\generate_openapi.py
.venv\Scripts\ruff check src tests scripts
.venv\Scripts\ruff format --check src tests scripts
.venv\Scripts\mypy
.venv\Scripts\pytest --cov --basetemp .tmp-pytest-api -p no:cacheprovider
```

Тесты покрывают сервисы хранения, очереди, worker, приёма результата и feedback;
endpoint загрузки, каталога пакетов, создания и polling review, выдачи findings и feedback;
параллельный polling, отсутствующие объекты, безопасные ошибки и соответствие сохранённого
OpenAPI фактическому приложению.
