# 14. Production-развитие

## Цель

Превратить демонстрационное приложение в изолированную on-premise платформу для компаний с большими корпусами документов.

## Предпосылки

- подтверждена полезность MVP;
- известны требования первой production-компании;
- согласованы SLA, безопасность и объёмы;
- Analysis Core имеет стабильный versioned contract.

## Поток A. Multi-company и доступ

### Задачи

- tenant-aware data model;
- строгая фильтрация по `company_id`;
- SSO/OIDC;
- роли analyst, reviewer, pack-admin, platform-admin;
- политики доступа к документам и Review Packs;
- tenant isolation tests;
- аудит административных операций.

### Результат

Данные, файлы, индексы и результаты компаний изолированы на каждом уровне.

## Поток B. Надёжное хранение

### Задачи

- MinIO/S3;
- encryption at rest и in transit;
- retention policies;
- удаление документа и производных артефактов;
- backup/restore PostgreSQL и object storage;
- контроль целостности;
- legal hold при необходимости.

### Результат

Хранение соответствует требованиям корпоративного контура и восстанавливается после сбоя.

## Поток C. Масштабирование исполнения

### Задачи

- Celery/RabbitMQ или согласованный job broker;
- отдельные parser и analysis worker pools;
- concurrency limits на tenant/model;
- quotas и priorities;
- idempotency;
- retries и dead-letter handling;
- graceful shutdown;
- capacity testing на больших документах.

### Результат

Параллельные проверки не блокируют API и предсказуемо используют GPU/CPU.

## Поток D. Review Pack Registry

### Задачи

- draft/published/deprecated;
- immutable versions;
- validation и compatibility checks;
- approval workflow;
- regression gate от Михаила;
- diff и rollback;
- каталог пакетов и прав доступа;
- импорт/экспорт пакетов.

### Результат

Компания управляет правилами проверки как версионируемым продуктом.

## Поток E. Корпоративный корпус

### Задачи

- ingestion API;
- полнотекстовый индекс;
- pgvector при подтверждённой необходимости;
- ACL-aware retrieval;
- обновление и удаление индекса;
- ссылки на источники;
- запрет межтенантного retrieval;
- измерение качества поиска.

### Результат

Analysis Core получает разрешённый контекст из большого корпуса без передачи всего массива модели.

## Поток F. On-premise Model Gateway

### Задачи

- vLLM/OpenAI-compatible endpoint;
- поддержка корпоративных Qwen/Kimi;
- model routing;
- health, timeout и rate limits;
- GPU monitoring;
- контроль версий моделей;
- отсутствие внешнего egress;
- нагрузочные и качественные тесты перед переключением.

### Результат

Документы не покидают контур компании, а модель заменяется без изменения приложения.

## Поток G. Интеграции

### Приоритет

1. REST API.
2. Confluence/SharePoint import.
3. Git/CI quality gate.
4. Системы управления требованиями.
5. Пакетная проверка существующего корпуса.

Каждый connector обязан соблюдать tenant ACL, versioning источника и идемпотентность.

## Поток H. Наблюдаемость и безопасность

### Задачи

- OpenTelemetry traces;
- Prometheus metrics;
- dashboards и alerts;
- audit log;
- secret manager;
- vulnerability/dependency scanning;
- SBOM;
- data classification;
- redaction в логах;
- disaster recovery runbook.

### Основные SLI

- время ожидания job;
- длительность анализа;
- доля успешных запусков;
- ошибки parser/model/contract;
- backlog очереди;
- доступность API и Model Gateway;
- объём хранилища.

## Порядок production-внедрения

```text
1. Security и tenant boundaries
2. Надёжное object storage
3. Устойчивая очередь и workers
4. SSO/RBAC/audit
5. Внутренний Model Gateway
6. Review Pack Registry
7. Первый connector
8. Корпоративный search/index
9. Горизонтальное масштабирование
```

## Критерий завершения

Платформа развёртывается внутри инфраструктуры компании, изолирует tenants, использует внутреннюю модель, управляет версиями Review Packs и проходит согласованные security, load и recovery проверки.

