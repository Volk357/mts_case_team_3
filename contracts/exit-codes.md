# Exit codes Analysis Core

Product Application принимает решение по exit code и структурированному `error.code`. Текст `stderr` используется только для диагностики.

| Exit code | Типовые `error.code` | Повтор | Значение |
|---:|---|---|---|
| `0` | — | — | Анализ завершён, `status=completed` |
| `2` | `INVALID_ARGUMENTS` | Нет | Ошибка аргументов CLI |
| `3` | `DOCUMENT_READ_ERROR`, `DOCUMENT_PARSE_ERROR`, `UNSUPPORTED_DOCUMENT` | Нет | Файл нельзя прочитать или разобрать |
| `4` | `REVIEW_PACK_NOT_FOUND`, `REVIEW_PACK_INVALID`, `REVIEW_PACK_INCOMPATIBLE` | Нет | Review Pack отсутствует или невалиден |
| `5` | `MODEL_UNAVAILABLE`, `MODEL_TIMEOUT` | Да | Временная ошибка модели |
| `5` | `MODEL_AUTH_FAILED`, `MODEL_CONFIG_INVALID` | Нет | Конфигурация или доступ к модели неверны |
| `6` | `MODEL_RESPONSE_INVALID` | Да | Ответ модели остался невалидным после внутренних повторов |
| `7` | `INTERNAL_ERROR` | Нет | Непредвиденная ошибка pipeline |
| `8` | `ANALYSIS_TIMEOUT` | Да | Превышен общий timeout |
| `8` | `ANALYSIS_CANCELLED` | Нет | Запуск отменён вызывающей стороной |

## Правила обработки

- При `0` результат обязан пройти JSON Schema и дополнительные инварианты приложения.
- Нулевой exit code без валидного результата считается `CORE_RESULT_INVALID` на стороне Product Application.
- Неизвестный ненулевой exit code считается `CORE_PROCESS_FAILED` и не повторяется автоматически.
- Поле `error.retriable` уточняет таблицу, но не заставляет приложение выполнять автоматический повтор.
- Повтор создаёт новый процесс, но сохраняет исходный `run_id`, если это внутренний retry одного job.
- Пользовательский повтор после terminal state создаёт новый `ReviewJob` и новый `run_id`.

