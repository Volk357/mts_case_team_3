# 06. Backend API

## Цель

Предоставить frontend стабильный HTTP-интерфейс для полного пользовательского сценария.

## Зависимости

- модели данных;
- upload service;
- Review Job Runner;
- контракты результатов и ошибок.

## Последовательность работ

### NIK-06-01. API conventions

**Статус:** выполнено 3 сентября 2026 года.

- зафиксировать prefix `/api`;
- использовать UUID/opaque IDs;
- определить единый error envelope;
- нормализовать даты в UTC/ISO 8601;
- отделить transport schemas от ORM;
- включить OpenAPI.

### NIK-06-02. Documents API

**Статус:** выполнено 3 сентября 2026 года.

- `POST /api/documents`;
- `GET /api/documents/{id}` при необходимости;
- проверять существование файла;
- не раскрывать storage path;
- корректно обрабатывать повторную загрузку одинакового файла.

### NIK-06-03. Reviews API

**Статус:** выполнено 3 сентября 2026 года.

- `POST /api/reviews`;
- `GET /api/reviews/{id}`;
- `GET /api/reviews/{id}/findings`;
- определить polling interval recommendation;
- возвращать stage без внутренних prompt/model деталей;
- не блокировать запрос до окончания анализа.

### NIK-06-04. Review Packs API

- `GET /api/review-packs`;
- возвращать ID, display name, document type и version;
- показывать только валидные и опубликованные/разрешённые пакеты;
- не позволять frontend передавать произвольный filesystem path.

### NIK-06-05. Feedback API

- `POST` или `PUT /api/findings/{id}/feedback`;
- валидировать решение;
- поддержать изменение решения;
- отделить пользовательский комментарий от Finding.

### NIK-06-06. Ошибки и безопасность

- централизованный exception handler;
- безопасные тексты для пользователя;
- request size limits;
- CORS allowlist;
- базовая rate limiting точка расширения;
- correlation ID;
- исключить секреты и внутренние пути из ответа.

### NIK-06-07. Документация и тесты

- примеры запросов/ответов;
- generated OpenAPI;
- unit tests services;
- integration tests endpoints;
- тесты concurrent polling и отсутствующих объектов.

## Артефакты

- FastAPI endpoints;
- OpenAPI schema;
- error catalog;
- API tests;
- frontend API client contract.

## Проверки

- полный сценарий выполняется только через API;
- создание review возвращает быстро;
- polling стабильно отражает состояние;
- завершённый result соответствует CLI;
- неизвестный pack и document дают разные ошибки;
- API не раскрывает внутренние пути и секреты.

## Критерий завершения

Через HTTP можно загрузить документ, создать review, дождаться завершения, получить findings и сохранить feedback.
