# Второй платформенный профиль

Пара `generic-tech-spec/1.0` и `generic-notification-service.docx` показывает
подключение нового типа документа без изменений приложения и Analysis Core.

## Демонстрация

1. Запустить окружение по `docs/docker-compose-runbook.md`.
2. Повторно выполнить `seed-demo`, чтобы каталог зарегистрировал оба Review Pack.
3. Открыть экран загрузки и выбрать «Универсальная техническая спецификация».
4. Загрузить `examples/platform-showcase/generic-notification-service.docx`.
5. После проверки показать категории generic-профиля, например
   `AMBIGUOUS_REQUIREMENT`, `INCOMPLETE_API_CONTRACT`,
   `SECURITY_REQUIREMENT_GAP` и `ACCEPTANCE_CRITERIA_MISSING`.

Пример намеренно содержит несколько дефектов: субъективную характеристику
скорости, незаполненный таймаут, неполный API-контракт, неопределенную
авторизацию и непроверяемый критерий приемки.
