# 11. Docker Compose

## Цель

Обеспечить воспроизводимый запуск демонстрационного продукта одной командой.

## Зависимости

- работающие frontend, backend и worker;
- выбранный способ установки Analysis Core;
- PostgreSQL migrations;
- конфигурация model endpoint.

## Последовательность работ

### NIK-11-01. Backend image

- multi-stage Dockerfile при необходимости;
- фиксированные зависимости;
- непривилегированный пользователь;
- установка Product Application и Analysis Core;
- отдельные команды API и worker;
- health check.

### NIK-11-02. Frontend image

- production build;
- статическая раздача или frontend server;
- runtime API URL без пересборки, если возможно;
- health check;
- корректная работа SPA routes.

### NIK-11-03. PostgreSQL

- persistent volume;
- health check;
- безопасные demo credentials через `.env`;
- migrations до старта API/worker;
- seed только в явном demo-режиме.

### NIK-11-04. Volumes

- documents storage;
- runs storage;
- Review Packs read-only;
- диагностические артефакты;
- проверить владельцев и права внутри контейнеров.

### NIK-11-05. Model connectivity

- внешний API через конфигурацию;
- локальный OpenAI-compatible endpoint через доступный host address;
- health/preflight проверка;
- секреты только через environment/secrets;
- понятная диагностика недоступного endpoint.

### NIK-11-06. Compose orchestration

- сервисы `frontend`, `api`, `worker`, `postgres`;
- добавить `redis` при использовании Celery;
- dependency health conditions;
- restart policies для demo;
- resource limits, если они не мешают модели;
- profiles `mock` и `real`.

### NIK-11-07. Документация

- копирование `.env.example`;
- команды build/up/down/logs;
- migrations;
- переключение mock/real;
- подключение локальной модели;
- проверка health.

## Артефакты

- Dockerfiles;
- `docker-compose.yml`;
- `.env.example`;
- health checks;
- volumes;
- инструкция запуска.

## Проверки

- clean build без локальных кешей;
- запуск после удаления контейнеров;
- данные переживают restart;
- Review Packs доступны read-only;
- mock profile работает без model endpoint;
- real profile корректно диагностирует отсутствие модели.

## Критерий завершения

Новый участник поднимает приложение по README одной основной командой и выполняет happy path без ручной настройки контейнеров.

