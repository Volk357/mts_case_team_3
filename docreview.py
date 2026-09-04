#!/usr/bin/env python3
"""CLI `docreview` — мост Analysis Core → Product Application по контракту v1.0.

Команда:
    docreview analyze --file <doc> --pack <review_pack> --run-id <id> --output <out.json>

Гоняет наш пайплайн (детерминированный слой + модель) и пишет ReviewResult JSON
по схеме contracts/review-result.schema.json. location.section_path берётся из
нашего детектора разделов; page/таблицы — POST-submission (page=null).

Ядро не знает про UI/HTTP/БД приложения — только файл на входе, JSON на выходе.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time

ENGINE_VERSION = "0.2.0"
SCHEMA_VERSION = "1.0"

# Каталог самого ядра. Приложение запускает нас с рабочим каталогом своего
# workspace (process_runner: cwd=request.workspace.root), а конфиги ядра лежат
# рядом с этим файлом. Без этого template.yaml/defects.yaml не находятся.
CORE_DIR = os.path.dirname(os.path.abspath(__file__))


def _core_path(name):
    """Путь к конфигу ядра.

    Голое имя («template.yaml») всегда разрешается РЯДОМ С ЯДРОМ, а не
    относительно рабочего каталога: иначе файл с таким же именем, случайно
    лежащий в workspace приложения, молча подменил бы наши правила.
    Явный путь (абсолютный или с разделителем) используется как передан.
    """
    return name if os.path.isabs(name) or os.sep in name \
        else os.path.join(CORE_DIR, name)


# Коды и exit codes — из contracts/exit-codes.md, а не свои. Прежние
# CORE_UNSUPPORTED_FORMAT / CORE_INPUT_UNREADABLE / CORE_PROCESS_FAILED
# в каталоге приложения отсутствуют: приложение считало их неизвестными
# и превращало в CORE_PROCESS_FAILED без возможности повтора.
EXIT_INVALID_ARGUMENTS = 2
EXIT_DOCUMENT = 3          # DOCUMENT_READ_ERROR, DOCUMENT_PARSE_ERROR, UNSUPPORTED_DOCUMENT
EXIT_REVIEW_PACK = 4       # REVIEW_PACK_NOT_FOUND, REVIEW_PACK_INVALID
EXIT_MODEL = 5             # MODEL_UNAVAILABLE, MODEL_TIMEOUT
EXIT_INTERNAL = 7          # INTERNAL_ERROR

# Наш severity → enum контракта (critical/high/medium/low). clarification → low.
_SEV_MAP = {"high": "high", "medium": "medium", "low": "low",
            "clarification": "low", "critical": "critical"}
_SEV_BASE = {"high": 0.85, "medium": 0.7, "low": 0.55, "clarification": 0.5,
             "critical": 0.9}


def _block_id(quote):
    return "q-" + hashlib.sha1((quote or "").encode("utf-8")).hexdigest()[:12]


def _confidence(finding, deterministic):
    if deterministic:
        return 0.95
    base = _SEV_BASE.get(finding.get("severity", "medium"), 0.6)
    base += 0.05 * (int(finding.get("merged_count", 1)) - 1)
    return round(max(0.05, min(0.99, base)), 2)


def _section_path(quote, lines, cfg, is_section_header):
    """Ближайший заголовок раздела шаблона выше цитаты. Настоящий section_path."""
    if not quote:
        return []
    head = quote.split("\n", 1)[0].strip()
    idx = next((i for i, ln in enumerate(lines) if head and head in ln), None)
    if idx is None:
        return []
    for j in range(idx, -1, -1):
        if is_section_header(lines[j], cfg):
            name = re.sub(r"\s+", " ", lines[j].strip())
            return [name]
    return []


def _map_finding(f, i, deterministic, lines, cfg, is_section_header):
    quote = f.get("quote", "") or ""
    did = f.get("defect_id", "UNKNOWN")
    if not re.match(r"^[A-Z][A-Z0-9_]*$", did):
        did = "UNKNOWN"
    return {
        "id": "f-%03d" % i,
        "defect_id": did,
        "severity": _SEV_MAP.get(f.get("severity", "medium"), "medium"),
        "confidence": _confidence(f, deterministic),
        "location": {
            "page": None,
            "section_path": _section_path(quote, lines, cfg, is_section_header),
            "block_id": _block_id(quote),
        },
        "quote": quote or "—",
        "problem": (f.get("explanation") or "Место требует уточнения.").strip() or "—",
        "clarification": (f.get("suggestion") or "Уточнить у аналитика.").strip() or "—",
        "detected_by": ["deterministic"] if deterministic else ["model"],
    }


BUDGET = 20                       # контракт: findings maxItems 20


def _rank_union(formal_findings, llm_findings, ceiling=BUDGET):
    """Объединяет слои под потолок контракта по ОДНОМУ правилу ранжирования.

    Раньше здесь был срез `findings[:20]` по позиции: формальные, затем
    модельные. При большом числе формальных находок хвост модельных, включая
    high, отваливался молча — вопреки заявленному «high не режется».

    Правило: не режем high и детерминированные (формальный слой точен по
    построению, галлюцинаций не даёт); остаток добираем по severity ×
    confidence — той же `run_review.apply_budget`, что работает внутри слоя
    модели, чтобы правило было одно, а не два. Если одних защищённых больше
    потолка, режем и их (схема контракта не допускает больше 20): сначала по
    severity, внутри severity — детерминированные вперёд, дальше по важности.

    Отбор и порядок выдачи — разные вещи. Защищённость решает, кто попадёт в
    выдачу; порядок в ней — общий для всех: severity, затем severity ×
    confidence, детерминированное вперёд при равенстве. Иначе
    детерминированный low встал бы выше модельного medium. Порядок
    применяется всегда, а не только при переполнении: выдача не меняет
    порядок в зависимости от объёма.

    Возвращает список пар (находка, детерминированная_ли).
    """
    import run_review                            # ранжирование — общее с run_full
    union = ([(f, True) for f in formal_findings]
             + [(f, False) for f in llm_findings])
    protected = [(f, d) for f, d in union if d or run_review._sev_rank(f) == 0]
    rest = [(f, d) for f, d in union if not (d or run_review._sev_rank(f) == 0)]

    # 1. Отбор: защищённые вперёд, при их переполнении режем по severity,
    #    внутри severity — детерминированные вперёд, дальше по важности.
    protected.sort(key=lambda p: run_review._priority(p[0]), reverse=True)
    protected.sort(key=lambda p: (run_review._sev_rank(p[0]), 0 if p[1] else 1))
    rest.sort(key=lambda p: run_review._priority(p[0]), reverse=True)
    slots = max(0, ceiling - len(protected))
    kept = (protected + rest[:slots])[:ceiling]

    # 2. Порядок выдачи: три устойчивые сортировки, последняя — главная.
    kept.sort(key=lambda p: 0 if p[1] else 1)
    kept.sort(key=lambda p: run_review._priority(p[0]), reverse=True)
    kept.sort(key=lambda p: run_review._sev_rank(p[0]))
    return kept


def build_review_result(text, filename, document_type, formal_findings,
                        llm_findings, run_id, pack, model_name,
                        prompt_versions, total_ms, warnings=None,
                        total_candidates=None, verified_candidates=None, cfg=None,
                        document_sha256=None):
    """Чистая сборка ReviewResult (completed). Тестируется без модели.

    cfg — уже загруженный шаблон (из Review Pack, если он его содержит). Если
    не передан, берём шаблон рядом с ядром: путь обязан быть абсолютным, потому
    что приложение запускает нас со своим рабочим каталогом.
    """
    import check_formal
    # pack — либо (id, version), либо просто id (обратная совместимость тестов)
    pack_id, pack_version = pack if isinstance(pack, (tuple, list)) \
        else (pack, DEFAULT_PACK_VERSION)
    if cfg is None:
        cfg = check_formal.load_config(_core_path("template.yaml"))
    is_sh = check_formal.is_section_header
    lines = text.splitlines()

    findings = [_map_finding(f, i, det, lines, cfg, is_sh) for i, (f, det)
                in enumerate(_rank_union(formal_findings, llm_findings))]

    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for f in findings:
        counts[f["severity"]] += 1

    n = len(formal_findings) + len(llm_findings)
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "status": "completed",
        "document": {
            "filename": filename,
            "document_type": document_type,
            # Хеш ФАЙЛА, а не текста: приложение сверяет его с загруженным
            # документом. Запасной вариант по тексту оставлен для тестов,
            # которые собирают результат без файла на диске.
            "sha256": document_sha256 or hashlib.sha256(text.encode("utf-8")).hexdigest(),
        },
        "engine": {"version": ENGINE_VERSION},
        "review_pack": {"id": pack_id, "version": pack_version},
        "model": {"name": model_name, "prompt_versions": prompt_versions},
        "findings": findings,
        "summary": {
            "total_candidates": int(total_candidates if total_candidates is not None else n),
            "verified_candidates": int(verified_candidates if verified_candidates is not None else n),
            "returned_findings": len(findings),
            **counts,
        },
        "warnings": warnings or [],
        "timings": {"total_ms": int(total_ms)},
    }


def failed_result(run_id, code, stage, message, retriable):
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "status": "failed",
        "error": {"code": code, "stage": stage, "message": message,
                  "retriable": bool(retriable)},
    }


class UnsupportedBinary(Exception):
    """Файл двоичный: извлекать текст ядро не умеет (парсер — POST-submission)."""


# Сигнатуры двоичных контейнеров. Проверяются по содержимому, а не по
# расширению: .docx, переименованный в .txt, тоже должен быть отбит.
_BINARY_SIGNATURES = [
    (b"PK\x03\x04", "xlsx/pptx (zip-контейнер, но не docx)"),
    (b"%PDF", "pdf"),
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "doc/xls (OLE2)"),
    (b"{\\rtf", "rtf"),
]


def _read_document(path):
    """Читает документ. Возвращает (текст, тип, предупреждения, sha256 ФАЙЛА).

    Хеш считается по БАЙТАМ файла, а не по извлечённому тексту: приложение
    сверяет `document.sha256` из результата с хешем загруженного файла и при
    расхождении бракует результат целиком. Для .docx хеш текста не совпал бы
    никогда — на этом сквозной сценарий и падал.

    txt/md читаются напрямую, .docx разбирается своим экстрактором,
    прочие двоичные форматы — честный отказ.

    Двоичный вход отбивается ДО анализа. Иначе .docx читается как мусор,
    детерминированный слой срабатывает на строке вида «PK..[Content_Types].xml»,
    и наружу это выглядит как валидный ответ, а не как ошибка (проверено на
    реальном документе 4 сентября). Честный отказ лучше правдоподобной ерунды.
    Извлечение текста из pdf/docx — задача приложения (или POST-submission).
    """
    with open(path, "rb") as fh:
        raw = fh.read()
    digest = hashlib.sha256(raw).hexdigest()

    # .docx разбираем сами: таблицы нужны строками «ячейка | ячейка», а адреса
    # гиперссылок — рядом с текстом. Плоская конвертация теряет и то и другое,
    # из-за чего проверка ссылок ругалась на ссылку, которая в документе есть.
    if raw.startswith(b"PK\x03\x04"):
        import docx_text
        try:
            text = docx_text.extract(path)
        except docx_text.NotADocx as e:
            raise UnsupportedBinary(
                "Файл — zip-контейнер, но не .docx (%s). Ядро принимает "
                ".docx и извлечённый текст (txt/md)." % e)
        warn = []
        if not docx_text.count_links(path):
            warn.append({
                "code": "NO_EXTERNAL_LINKS",
                "message": "В документе нет внешних гиперссылок. Замечания об "
                           "отсутствующих ссылках следует читать с учётом этого: "
                           "возможно, ссылки были потеряны при подготовке файла."})
        return text, "docx", warn, digest

    for sig, what in _BINARY_SIGNATURES:
        if raw.startswith(sig):
            raise UnsupportedBinary(
                "Файл в формате %s: ядро принимает .docx и извлечённый текст "
                "(txt/md). Для остальных форматов извлеките текст на стороне "
                "приложения." % what)
    if b"\x00" in raw[:8192]:
        raise UnsupportedBinary(
            "Файл двоичный (NUL-байты в начале): ядро принимает только "
            "извлечённый текст (txt/md).")

    text = raw.decode("utf-8", errors="replace")
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    if ext in ("txt", "md", "markdown", ""):
        return text, ext or "txt", [], digest
    # Расширение не текстовое, но содержимое — текст (например, приложение уже
    # извлекло его и сохранило под исходным именем). Работаем, но предупреждаем.
    warn = [{"code": "PARSER_FALLBACK",
             "message": "Формат %s без структурного парсера; содержимое прочитано "
                        "как текст, привязка к странице/таблице недоступна." % ext}]
    return text, ext, warn, digest


DEFAULT_PACK_ID = "mts-net"
DEFAULT_PACK_VERSION = "0.2"
PACK_MANIFEST_NAMES = ("pack.yaml", "pack.yml", "manifest.yaml", "manifest.yml")
_VERSION_SEGMENT = re.compile(r"^v?\d+(?:\.\d+)*$")


def _verified_formal(result, text, warnings):
    """Оставляет детерминированные находки, чья цитата есть в документе побуквенно.

    До этого проверка существовала только в самостоятельном CLI check_formal,
    где она печатала предупреждение и ничего не отбрасывала, а боевой путь брал
    `findings` напрямую. Получалось, что тезис «замечание без совпадения с текстом
    отбрасывается» держался на построении проверок, а не на коде.

    Цена измерена перед внесением: на 5 synth-документах и их чистых версиях,
    на извлечённом .docx и на трёх реальных документах — 42 находки, ни одна
    не отсеивается. То есть это страховка от будущей правки регулярки, а не
    фильтр, меняющий полноту сегодня. Если он всё же сработает, наружу уйдёт
    предупреждение: молча терять находку хуже, чем показать её потерю.
    """
    import check_formal                      # импорт локальный, как везде в модуле:
                                            # ядро запускается и из чужого cwd
    findings = result["findings"]
    bad = check_formal.verify_quotes(result, text)
    if not bad:
        return findings
    warnings.append({
        "code": "FORMAL_QUOTE_NOT_FOUND",
        "message": ("Детерминированных замечаний отброшено: %d — цитата не найдена "
                    "в документе побуквенно. Это дефект проверки, а не документа."
                    % len(bad)),
    })
    dropped = set(bad)
    return [f for f in findings if f["quote"] not in dropped]


def resolve_pack(pack):
    """Разбирает `--pack`: путь к каталогу пакета ИЛИ к его manifest-файлу
    (так это описано в INTEGRATION_CONTRACT.md), либо голый идентификатор.

    Возвращает (id, version, template, defects, glossary, warnings).

    Почему id и version важны: приложение сверяет `review_pack.id`
    и `review_pack.version` в результате с тем, что записано в задании,
    и при расхождении бракует результат целиком — даже при exit 0.
    Поэтому источник истины — манифест ВНУТРИ пакета (за содержимое пакета
    по контракту отвечает наша сторона), а не догадки по имени каталога.

    Если манифеста нет, применяется соглашение о раскладке
    `<review-packs>/<pack_key>/<version>`: приложение резолвит локатор вида
    «requirements/1.0» относительно своего корня пакетов. Тогда версия — это
    последний сегмент пути, а идентификатор — предыдущий. Если и это не
    распознаётся, возвращаются значения по умолчанию И предупреждение
    в результат: молча подставлять чужую версию нельзя, приложение
    забракует результат, а причина будет неочевидна.
    """
    if not pack:
        return DEFAULT_PACK_ID, DEFAULT_PACK_VERSION, None, None, None, []
    looks_like_path = os.sep in pack or pack.endswith((".yaml", ".yml", ".json", "/"))
    if not looks_like_path:
        return pack, DEFAULT_PACK_VERSION, None, None, None, []
    if not os.path.exists(pack):
        raise ReviewPackMissing(pack)

    if os.path.isfile(pack):
        manifest_path, base = pack, os.path.dirname(os.path.abspath(pack))
    else:
        base = os.path.abspath(pack.rstrip(os.sep))
        manifest_path = next((os.path.join(base, n) for n in PACK_MANIFEST_NAMES
                              if os.path.isfile(os.path.join(base, n))), None)

    warnings, pack_id, version = [], None, None
    if manifest_path:
        import yaml
        try:
            man = yaml.safe_load(open(manifest_path, encoding="utf-8")) or {}
        except Exception as e:                      # noqa: BLE001
            raise ReviewPackInvalid("манифест %s не читается: %s" % (manifest_path, e))
        if not isinstance(man, dict):
            raise ReviewPackInvalid("манифест %s: ожидался словарь" % manifest_path)
        pack_id = man.get("id") or man.get("pack_key")
        version = man.get("version")
        version = str(version) if version is not None else None
        # Манифест объявлен источником истины — значит он обязан быть полным.
        # Иначе получилась бы худшая из ситуаций: манифест есть, а идентичность
        # тихо достроена из пути, и приложение бракует результат без причины.
        missing = [k for k, v in (("id/pack_key", pack_id), ("version", version)) if not v]
        if missing:
            raise ReviewPackInvalid(
                "манифест %s не объявляет: %s" % (manifest_path, ", ".join(missing)))

    if not (pack_id and version):
        segments = [x for x in base.split(os.sep) if x]
        if len(segments) >= 2 and _VERSION_SEGMENT.match(segments[-1]):
            pack_id = pack_id or segments[-2]
            version = version or segments[-1]
        else:
            pack_id = pack_id or (os.path.basename(base) or DEFAULT_PACK_ID)
            version = version or DEFAULT_PACK_VERSION
            warnings.append({
                "code": "REVIEW_PACK_VERSION_ASSUMED",
                "message": ("В пакете нет манифеста (%s), и путь не в раскладке "
                            "<pack_key>/<version>. id и версия выведены как «%s»/«%s» — "
                            "если приложение ожидает другие, результат будет забракован "
                            "как несоответствующий заданию."
                            % ("/".join(PACK_MANIFEST_NAMES), pack_id, version))})

    def in_pack(name):
        path = os.path.join(base, name)
        return path if os.path.isfile(path) else None

    return (pack_id, version, in_pack("template.yaml"), in_pack("defects.yaml"),
            in_pack("glossary.yaml"), warnings)


MODEL_CONFIG_ENV = "DOCREVIEW_MODEL_CONFIG"
MODEL_CONFIG_DEFAULT = "model-config.yaml"


def find_model_config(explicit=None):
    """Где взять параметры модели, по убыванию приоритета.

    1. `--model-config` — как описано в контракте;
    2. переменная окружения DOCREVIEW_MODEL_CONFIG;
    3. `model-config.yaml` рядом с ядром.

    Пункты 2 и 3 нужны не для красоты. `ProcessRunner` вычищает окружение
    дочернего процесса, а `AnalysisJobExecutor` собирает `AnalysisProcessRequest`
    без `model_config_path` — значит `--model-config` приложение сейчас
    не передаёт вообще, и ядро осталось бы без эндпоинта модели. Пока это
    не поправлено на стороне приложения, конфиг рядом с ядром позволяет
    развернуть рабочий контур, не трогая чужой код.
    """
    if explicit:
        return explicit
    from_env = os.environ.get(MODEL_CONFIG_ENV)
    if from_env:
        return from_env
    beside_core = os.path.join(CORE_DIR, MODEL_CONFIG_DEFAULT)
    return beside_core if os.path.isfile(beside_core) else None


def load_model_config(path):
    """Параметры модели из YAML или JSON.

    Понимаем ключи: base_url | url | endpoint, model | name, num_ctx, timeout.
    Возвращает словарь; пустой, если путь не задан.
    """
    if not path:
        return {}
    if not os.path.isfile(path):
        raise ModelConfigInvalid("файл конфигурации модели не найден: %s" % path)
    import yaml
    try:
        conf = yaml.safe_load(open(path, encoding="utf-8")) or {}
    except Exception as e:                          # noqa: BLE001
        raise ModelConfigInvalid("%s не читается: %s" % (path, e))
    if not isinstance(conf, dict):
        raise ModelConfigInvalid("%s: ожидался словарь" % path)
    url = conf.get("base_url") or conf.get("url") or conf.get("endpoint")
    out = {"url": url, "model": conf.get("model") or conf.get("name")}
    # Числовые параметры приводим ЗДЕСЬ: если сделать это позже, ошибка
    # значения уедет в общий обработчик и вернётся как INTERNAL_ERROR (exit 7)
    # вместо MODEL_CONFIG_INVALID (exit 5).
    for key in ("num_ctx", "timeout"):
        raw = conf.get(key)
        if raw is None:
            out[key] = None
            continue
        # bool — подкласс int, а int(1.5) молча даёт 1: и то и другое
        # означает, что в конфиге написано не то, что имели в виду.
        if isinstance(raw, bool) or not isinstance(raw, (int, str)):
            raise ModelConfigInvalid(
                "%s: параметр %s должен быть целым числом, получено %r"
                % (path, key, raw))
        try:
            out[key] = int(str(raw).strip())
        except (TypeError, ValueError):
            raise ModelConfigInvalid(
                "%s: параметр %s должен быть целым числом, получено %r"
                % (path, key, raw))
        if out[key] <= 0:
            raise ModelConfigInvalid(
                "%s: параметр %s должен быть положительным, получено %r"
                % (path, key, raw))
    return out


class ReviewPackMissing(Exception):
    """Каталог или манифест Review Pack, переданный приложением, не существует."""


class ReviewPackInvalid(Exception):
    """Пакет найден, но его содержимое нельзя разобрать."""


class ModelConfigInvalid(Exception):
    """Конфигурация модели не найдена или не разбирается."""


class ModelUnavailable(Exception):
    """Модель недоступна: сеть, таймаут или отказ эндпоинта."""


def cmd_analyze(args):
    t0 = time.time()
    run_id = args.run_id
    try:
        text, doc_type, warnings, document_sha256 = _read_document(args.file)
    except UnsupportedBinary as e:
        _write(args.output, failed_result(run_id, "UNSUPPORTED_DOCUMENT",
                                          "read", str(e), False))
        return EXIT_DOCUMENT
    except OSError as e:
        _write(args.output, failed_result(run_id, "DOCUMENT_READ_ERROR",
                                          "read", str(e), False))
        return EXIT_DOCUMENT

    try:
        (pack_id, pack_version, pack_template, pack_defects, pack_glossary,
         pack_warnings) = resolve_pack(args.pack)
        warnings = list(warnings) + pack_warnings
    except ReviewPackMissing as e:
        _write(args.output, failed_result(
            run_id, "REVIEW_PACK_NOT_FOUND", "analyze",
            "Review Pack не найден: %s" % e, False))
        return EXIT_REVIEW_PACK
    except ReviewPackInvalid as e:
        _write(args.output, failed_result(
            run_id, "REVIEW_PACK_INVALID", "analyze", str(e), False))
        return EXIT_REVIEW_PACK

    try:
        model_conf = load_model_config(find_model_config(args.model_config))
    except ModelConfigInvalid as e:
        _write(args.output, failed_result(
            run_id, "MODEL_CONFIG_INVALID", "analyze", str(e), False))
        return EXIT_MODEL

    try:
        import requests
        import run_review
        import check_formal
        # Параметры модели из --model-config переопределяют окружение: до ядра,
        # запущенного приложением, переменные окружения не доходят.
        if model_conf.get("url"):
            run_review.OLLAMA_URL = model_conf["url"]
        if model_conf.get("model"):
            run_review.MODEL = model_conf["model"]
        if model_conf.get("num_ctx"):
            run_review.NUM_CTX = model_conf["num_ctx"]
        if model_conf.get("timeout"):
            run_review.TIMEOUT = model_conf["timeout"]
        try:
            taxonomy_text, valid_ids, defects = run_review.load_taxonomy(
                pack_defects or _core_path(args.defects))
            if pack_glossary:
                # Глоссарий ЯДРА при сломанном yaml сознательно откатывается
                # на константу (его правит аналитик). Глоссарий ПАКЕТА — часть
                # версионируемого артефакта: сломанный файл обязан быть ошибкой,
                # поэтому разбираем его сами и только потом отдаём загрузчику.
                import yaml as _yaml
                _yaml.safe_load(open(pack_glossary, encoding="utf-8"))
            glossary_text = run_review.load_glossary(
                pack_glossary or _core_path(args.glossary))
            cfg = check_formal.load_config(pack_template or _core_path("template.yaml"))
        except Exception as e:                      # noqa: BLE001
            raise ReviewPackInvalid("не удалось разобрать правила пакета: %s" % e)
        known = run_review.extract_known_objects(text)
        formal = _verified_formal(check_formal.run(text, cfg), text, warnings)
        try:
            llm = run_review.run_full(text, defects, taxonomy_text, valid_ids, known,
                                      frag_mode="dict2", glossary_text=glossary_text,
                                      label="full2")
        except requests.exceptions.RequestException as e:
            raise ModelUnavailable(str(e))
        result = build_review_result(
            text, os.path.basename(args.file), doc_type, formal, llm["findings"],
            run_id, (pack_id, pack_version), run_review.MODEL,
            {"fragment": "dict2", "global": "global"},
            (time.time() - t0) * 1000, warnings,
            total_candidates=llm["found_raw"] + len(formal),
            verified_candidates=llm["verified"] + len(formal), cfg=cfg,
            document_sha256=document_sha256)
    except ModelUnavailable as e:
        # retriable=True: сеть или эндпоинт модели, повтор осмыслен
        _write(args.output, failed_result(run_id, "MODEL_UNAVAILABLE", "analyze",
                                          "Модель недоступна: %s" % e, True))
        return EXIT_MODEL
    except ReviewPackInvalid as e:
        _write(args.output, failed_result(run_id, "REVIEW_PACK_INVALID", "analyze",
                                          str(e), False))
        return EXIT_REVIEW_PACK
    except Exception as e:                          # noqa: BLE001 — любой сбой → failed
        _write(args.output, failed_result(run_id, "INTERNAL_ERROR", "analyze",
                                          str(e), False))
        return EXIT_INTERNAL

    _write_artifacts(args, llm, formal, result)
    _write(args.output, result)
    return 0


def _write_artifacts(args, llm, formal, result):
    """Диагностические артефакты прогона в `--artifacts-dir`.

    По контракту отклонённые кандидаты попадают ТОЛЬКО в debug-артефакты
    и никогда в ReviewResult: схема результата их не содержит. Поэтому
    `--include-rejected` управляет содержимым этого каталога, а не выдачи.
    Сбой записи артефактов не должен ронять успешный анализ.
    """
    directory = getattr(args, "artifacts_dir", None)
    if not directory:
        return
    try:
        os.makedirs(directory, exist_ok=True)
        payload = {
            "run_id": result["run_id"],
            "counters": {k: llm.get(k) for k in
                         ("found_raw", "verified", "rejected_count", "before_dedupe",
                          "merged_away", "capped_away", "severity_fixed")},
            "reject_reasons": llm.get("reject_reasons", {}),
            "formal_findings": len(formal),
        }
        if getattr(args, "include_rejected", False):
            payload["rejected"] = llm.get("rejected", [])
            payload["capped"] = llm.get("capped", [])
        with open(os.path.join(directory, "analysis-debug.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
    except OSError:
        pass                                        # артефакты не критичны для результата


def _write(path, obj):
    if path:
        json.dump(obj, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    else:
        json.dump(obj, sys.stdout, ensure_ascii=False, indent=2)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="docreview")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("analyze", help="проверить документ, выдать ReviewResult JSON")
    a.add_argument("--file", required=True)
    a.add_argument("--pack", default="mts-net-v0.2")
    a.add_argument("--run-id", required=True)
    a.add_argument("--output", default=None)
    a.add_argument("--defects", default="defects.yaml")
    a.add_argument("--glossary", default="glossary.yaml")
    # Флаги, которые process_runner приложения передаёт ВСЕГДА или по условию.
    # Без них argparse падал с exit 2 (INVALID_ARGUMENTS) на каждом запуске,
    # то есть сквозной сценарий не доходил до анализа вообще.
    a.add_argument("--artifacts-dir", default=None,
                   help="каталог для побочных артефактов прогона; ядро пишет "
                        "туда сырой ответ модели, если каталог существует")
    a.add_argument("--model-config", default=None,
                   help="принимается для совместимости с контрактом; параметры "
                        "модели ядро берёт из окружения (OLLAMA_URL/OLLAMA_MODEL)")
    a.add_argument("--include-rejected", action="store_true",
                   help="принимается для совместимости с контрактом; отклонённые "
                        "кандидаты в ReviewResult не входят (схема их не содержит)")
    args = ap.parse_args(argv)
    if args.cmd == "analyze":
        return cmd_analyze(args)
    return EXIT_INVALID_ARGUMENTS


if __name__ == "__main__":
    sys.exit(main())
