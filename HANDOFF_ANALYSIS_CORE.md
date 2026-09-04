# Analysis Core — передача Никите (интеграция)

Ветка `quality-core`. Это ядро анализа по контракту `INTEGRATION_CONTRACT.md`:
на входе файл, на выходе `ReviewResult` JSON по схеме `contracts/review-result.schema.json`.
Приложение вызывает ядро как CLI и НЕ содержит промптов/таксономии.

## Быстрый старт

```bash
# 1. Зависимости (Python 3.12): requests, pyyaml, python-pptx (для презы), jsonschema (тесты)
python3 -m pip install requests pyyaml jsonschema

# 2. Секреты — руками (в git не коммитятся)
cp .env.example .env          # затем вписать реальный OLLAMA_URL
set -a; source .env; set +a   # OLLAMA_URL, OLLAMA_MODEL в окружение

# 3. Вызов ядра (то, что делает process_runner приложения)
python3 docreview.py analyze \
    --file  data/synth/synth_3.txt \
    --pack  mts-net-v0.2 \
    --run-id demo-001 \
    --output result.json
# exit 0 + result.json (ReviewResult, status=completed) при успехе;
# exit ≠0 + result.json (status=failed, error.code) при сбое.
```

`result.json` **валиден по твоей JSON-схеме v1.0** (проверено `jsonschema` в
`test_docreview.py` и на реальном прогоне).

## CLI-контракт

| Флаг | Смысл |
|---|---|
| `--file` | путь к документу. **На вход ядра — только извлечённый текст (txt/md).** Двоичный файл (.docx/.pdf/.doc/.rtf — проверка по сигнатуре, а не по расширению) отбивается до анализа: `status=failed`, `error.code=CORE_UNSUPPORTED_FORMAT`, `retriable=false`, exit 3. Если текст уже извлечён, но сохранён под именем `*.docx`, ядро отработает и вернёт warning `PARSER_FALLBACK` |
| `--pack` | id Review Pack (сейчас дефолт `mts-net-v0.2`) |
| `--run-id` | идентификатор запуска (прокидывается в результат) |
| `--output` | путь для JSON (без флага — в stdout) |

> **Про формат входа (важно для демо).** Извлечение текста из DOCX/PDF — на стороне
> приложения. Раньше ядро читало .docx как текст и возвращало `status: completed` с
> замечанием на строке `PK..[Content_Types].xml` — правдоподобная ерунда вместо ошибки.
> Теперь двоичный вход отбивается честной ошибкой. Проверено на реальном .docx 4 сентября.

> **Про имя команды.** У нас файл `docreview.py`. В `process_runner` команду задать
> как `["python3", "<путь>/docreview.py"]` перед флагами. Если удобнее исполняемый
> `docreview` — заведём entry-point за 5 минут, скажи.

## Как наши находки маппятся в контракт

| Поле контракта | Источник у нас |
|---|---|
| `finding.defect_id` | тип из таксономии (25 типов) |
| `finding.severity` | наш severity; `clarification` → `low` |
| `finding.confidence` | прокси 0–1 (severity × согласие проходов) |
| `finding.problem` | наше `explanation` |
| `finding.clarification` | наше `suggestion` (рекомендация, текст НЕ переписываем) |
| `finding.detected_by` | `["deterministic"]` или `["model"]` |
| `finding.location.section_path` | **настоящий** — ближайший заголовок раздела шаблона |
| `finding.location.page` / `table` | `null` — POST-submission (нужен структурный парсер PDF/DOCX) |
| `summary`, `timings`, `document.sha256`, `engine`, `review_pack`, `model` | заполняются ядром |

`findings` ограничены 20 (бюджет), `high` не режется. Детерминированные типы
берутся ТОЛЬКО из формального слоя (модельные дубли этих типов отбрасываются).

## Что внутри ядра (файлы)

- `docreview.py` — CLI-мост под контракт (эта интеграция).
- `run_review.py` — пайплайн: нарезка, модель по фрагментам, кросс-фрагментный
  проход, верификация цитат, дедуп, бюджет. Эндпоинт/модель — из env.
- `check_formal.py` — детерминированный слой (регулярки + структура по `template.yaml`).
- `defects.yaml` / `defects_prompt.yaml` — таксономия / версия для промпта.
- `glossary.yaml`, `template.yaml` — глоссарий, конфиг шаблона (Review Pack).
- Генератор эталона: `model.py`, `domains.py`, `mutators.py`, `generate.py`, `score.py`.
- `data/synth/` — синтетический эталон (5 док., 65 дефектов) — воспроизводим `generate.py`.
- Тесты: `test_check_formal.py`, `test_score.py`, `test_run_review.py`, `test_docreview.py`
  (запуск `python3 <файл>`).

## Метрики (одна версия)

Полнота: по месту **65% (42/65)**, с типом 55% (36/65); слой детерм. **100% (16/16)**,
llm 53% (26/49). Точность: слепая внутренняя 83%, внешняя кейсодателя 58%.

## Границы и оговорки

- Только внутренняя LLM (локальная Qwen), эндпоинт из env, в репозиторий не коммитится.
- `page`/таблицы в `location` — заглушка (`null`) до структурного парсера — POST-submission.
- Текст за аналитика не переписываем (только место + характер проблемы).
- Замер полноты сделан один раз; разброс между прогонами — в план.

Вопросы по интеграции — пиши.
