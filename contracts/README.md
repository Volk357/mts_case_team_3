# Машинный контракт ReviewResult

## Файлы

- `review-result.schema.json` — JSON Schema Draft 2020-12 для версии 1.x;
- `examples/success.json` — валидный успешный результат;
- `examples/failure.json` — валидная ошибка;
- `examples/invalid` — негативные fixtures;
- `validate_contract.py` — schema и cross-field validation;
- `exit-codes.md` — стабильное сопоставление process/result ошибок;
- `CHANGELOG.md` — история версий контракта.

Человекочитаемым источником требований является [INTEGRATION_CONTRACT.md](../INTEGRATION_CONTRACT.md). При расхождении документа и схемы интеграция блокируется до согласования, а не выбирает одну трактовку молча.

## Запуск тестов

Из корня репозитория:

```powershell
python -m unittest discover -s tests -p "test_*.py"
```

Для тестов необходим `jsonschema>=4.23,<5`.

Он устанавливается воспроизводимо из lock-файла общей командой `npm run setup` или
отдельно:

```powershell
python -m pip install -r contracts/requirements.lock
```

## Генерация TypeScript-типов

Frontend должен генерировать типы из JSON Schema, а не поддерживать отдельную ручную копию:

```powershell
npm --prefix contracts install
npm --prefix contracts run generate:types
npm --prefix contracts run check
```

Результат создаётся в `contracts/generated/review-result.d.ts`. Frontend импортирует этот
файл напрямую через алиас `@contracts`; отдельная копия типов в приложении не поддерживается.
Вручную редактировать generated-файл нельзя.

Команда `check` также сравнивает сгенерированный файл со схемой и завершается ошибкой,
если схема была изменена без повторной генерации типов.

## Версионирование

- Schema принимает только версии `1.x`.
- Новые необязательные поля совместимы в пределах major 1.
- Новое обязательное поле, удаление или изменение смысла требует major 2.
- Product Application отклоняет неизвестную major-версию до разбора бизнес-полей.

JSON Schema не проверяет уникальность `finding.id` и согласованность summary с массивом. Эти инварианты проверяет `validate_review_result`.
