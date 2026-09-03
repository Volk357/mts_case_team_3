# Архитектура и текущий прогресс

## Поток данных

```mermaid
flowchart LR
    subgraph Company[Данные компании]
        T[Шаблон документа]
        X[Таксономия дефектов]
        E[Исключения и примеры]
        P[Промпты]
    end

    T --> RP[Версионируемый Review Pack / YAML]
    X --> RP
    E --> RP
    P --> RP

    A[Аналитик] -->|PDF или DOCX| U[Upload API]
    U -->|проверка типа и размера| FS[(Private document storage)]
    U --> D[(Application DB)]
    A -->|выбранный pack ID| J[Reviews API]
    J -->|queued job| D
    J -->|review ID, 202| A

    W[Review worker] -->|claim job| D
    W -->|file path + pack path + run ID| C[Analysis Core CLI]
    RP --> C
    C --> F[Детерминированные проверки]
    C --> L[LLM reviewers]
    L -->|OpenAI-compatible request| M[On-premise model gateway]
    F --> V[Verification, deduplication, ranking]
    L --> V
    V -->|ReviewResult JSON, max 20| W
    W -->|schema validation + atomic result| D

    A -->|poll status| J
    D -->|public stage/findings| J
    A -->|решение по finding| FB[Feedback API]
    FB --> D
    D -.->|обезличенная оценка| Q[Quality loop / следующая версия pack]
```

## Границы модулей

| Модуль | Получает | Возвращает | Не содержит |
|---|---|---|---|
| Product Application | Пользователя, файл, pack ID | UI, статусы, findings, feedback | Таксономию и prompts |
| Analysis Core | Путь к файлу, Review Pack, model config, run ID | JSON по общей схеме | HTTP, пользователей и UI |
| Review Pack | Шаблон, taxonomy, exclusions, prompts | Версионированные правила анализа | Код приложения и секреты |
| Model Gateway | Messages и параметры inference | Ответ модели | Документы в публичном облаке |

## Текущий статус

```mermaid
flowchart TD
    A[Готово: foundation и общий контракт] --> B[Готово: mock Core]
    B --> C[Готово: DB, upload, worker/runner]
    C --> D[Готово: Documents API и Reviews API]
    A --> E[Готово: quality pipeline]
    E --> F[Готово: synthetic golden set и scoring]
    D --> G[В работе: catalog Review Packs]
    F --> H[В работе: единая упаковка real Core]
    G --> I[Далее: progress/result UI и feedback]
    H --> I
    I --> J[Далее: E2E, второй pack, Docker и demo hardening]
```

## Что уже можно продемонстрировать

- запуск приложения одной командой и health diagnostics;
- загрузку валидного PDF/DOCX и отказ для небезопасного файла;
- создание review без блокировки HTTP-запроса;
- повторную отправку без дублирования job;
- polling `queued/running/completed/failed` и отдельную выдачу findings;
- mock-сценарии: 0, 12 и 20 findings, timeout, invalid JSON, model unavailable;
- генерацию пяти synthetic документов и их truth-разметки;
- архитектурную независимость приложения от prompts, модели и defect IDs.

## Что пока нельзя заявлять

- полностью завершённый UI просмотра результатов;
- production-ready развёртывание;
- доказанную экономию времени на реальной пользовательской выборке;
- финальный Recall@20;
- подтверждённую платформенность до работы второго Review Pack.
