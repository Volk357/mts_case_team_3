# Changelog интеграционного контракта

Все заметные изменения CLI и `ReviewResult` фиксируются здесь.

## 1.0 — 2026-09-03

- Зафиксирован executable `docreview` и команды `analyze`, `parse`, `validate-pack`, `version`.
- Зафиксированы обязательные аргументы `--file`, `--pack`, `--run-id`.
- Добавлены опциональные `--model-config`, `--output`, `--artifacts-dir`, `--include-rejected`.
- Зафиксированы правила UTF-8, stdout и stderr.
- Определены exit codes 0, 2–8.
- Определены успешный и ошибочный варианты `ReviewResult`.
- Зафиксированы обязательные `block_id` и `section_path`; `page` обязателен как поле, но может быть `null`; `bbox` опционален.
- Установлен жёсткий максимум 20 findings.
- Добавлены версии Analysis Core, Review Pack, модели и промптов.
- Разрешены новые необязательные поля в совместимых версиях 1.x.

