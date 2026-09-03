# API conventions

**Версия:** MVP, 3 сентября 2026 года.

## Публичная граница

- все продуктовые endpoint располагаются под неизменяемым prefix `/api`;
- интерактивная документация доступна по `/api/docs`, OpenAPI — по
  `/api/openapi.json`;
- transport-схемы находятся в `docreview_api.api.schemas` и не возвращают ORM-модели;
- идентификаторы ресурсов — непрозрачные UUID: клиент хранит и передаёт их как
  строки и не извлекает из них бизнес-смысл;
- даты обязаны содержать timezone и в JSON возвращаются в UTC/ISO 8601 с суффиксом
  `Z`, например `2026-09-03T12:00:00.000Z`;
- неизвестные поля входных transport-моделей отклоняются.

## Ошибки

Все ошибки имеют одну форму:

```json
{
  "error": {
    "code": "REQUEST_VALIDATION_ERROR",
    "message": "Request validation failed.",
    "details": [
      {
        "location": ["body", "document"],
        "reason": "Field required"
      }
    ]
  }
}
```

`error.code` — стабильный машинный код для логики клиента. `message` безопасен для
показа пользователю. `details` содержит только расположение и причину ошибки без
исходного значения поля. Внутренние пути, traceback, stderr, prompt и секреты в
HTTP-ответ не включаются.

Endpoint обязан объявить `ErrorEnvelope` в OpenAPI и преобразовывать ожидаемые
доменные ошибки в `ApiError`. Необработанная ошибка возвращается как безопасный
`INTERNAL_ERROR`; техническая причина остаётся в серверном журнале.

## Documents API

- `POST /api/documents` создаёт новый документ после проверки и атомарного сохранения;
- `GET /api/documents/{document_id}` возвращает только публичные метаданные и перед
  ответом проверяет наличие storage object;
- удалённый, чужой и неизвестный документ возвращают одинаковый
  `DOCUMENT_NOT_FOUND`;
- повреждение связи БД с хранилищем возвращает `DOCUMENT_FILE_UNAVAILABLE` без
  внутреннего пути;
- повторная загрузка тех же байтов создаёт новый UUID и отдельный жизненный цикл;
  SHA-256 используется только как внутренний индекс и не раскрывается клиенту.

## Reviews API

- `POST /api/reviews` принимает `document_id` и `review_pack_id`, требует заголовок
  `Idempotency-Key` и отвечает `202 Accepted`, не ожидая выполнения анализа;
- `GET /api/reviews/{review_id}` предназначен для polling. Для незавершённого review
  тело содержит `poll_after_ms`, а заголовок `Retry-After` — тот же интервал в секундах;
- публичная `stage` имеет только продуктовые значения `waiting`, `analysis`,
  `result_ready`, `finished`; PID, run ID, model, prompt versions и диагностика worker
  остаются внутри сервера;
- `GET /api/reviews/{review_id}/findings` возвращает замечания отдельно и в порядке
  `ordinal`; до появления результата допустим пустой список;
- повтор с тем же ключом и теми же параметрами возвращает существующий review, а
  использование ключа для другого запроса даёт `IDEMPOTENCY_CONFLICT`;
- неизвестные document, Review Pack и review различаются кодами `DOCUMENT_NOT_FOUND`,
  `REVIEW_PACK_NOT_FOUND` и `REVIEW_NOT_FOUND`.
