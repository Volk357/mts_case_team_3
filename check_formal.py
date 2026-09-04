#!/usr/bin/env python3
"""
Детерминированный слой проверок ТЗ. Без модели.

Проверяет пять вещей, требования по которым кейсодатель сформулировал
письменно (файлы «Шаблоны документации» и «Основные моменты
документации», присланы 3 сентября):

  TEMPLATE_SECTION_MISSING  раздел шаблона удалён, а не помечен «не применимо»
  NULLABILITY_UNSPECIFIED   у поля витрины нет NOT NULL / NULLABLE
  PLACEHOLDER_LEFT          осталась заглушка вместо значения
  DATA_CATALOG_MISSING      нет прямой ссылки на Дата-каталог
  HDFS_PATH_INCOMPLETE      упомянут HDFS, формат хранения не указан

Почему без модели. На этом классе дефектов правило формально и полно:
раздел либо есть, либо нет. Полнота получается сто процентов
по построению — проверка сама и есть эталон, измерять нечего.
Модель здесь дороже, медленнее и способна галлюцинировать там,
где регулярное выражение не способно.

Формат вывода совпадает с run_review.py, чтобы make_report.py
принимал результат без переделок.

Продуктовое решение по бюджету. Отсутствующие разделы выдаются ОДНИМ
замечанием со списком, а не по замечанию на раздел. В vitrina.txt
разделов не хватает больше десяти — россыпью они разорвали бы бюджет
10–15, названный кейсодателем, и вытеснили бы содержательные находки.
Бюджет про замечания, которые аналитик обдумывает; строка «отсутствуют
N обязательных разделов» обдумывания не требует.

Использование:
    python3 check_formal.py --doc vitrina.txt
    python3 check_formal.py --doc vitrina.txt --out results
"""

import argparse
import json
import re
from pathlib import Path

import yaml


def load_config(path):
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def lines_of(text):
    return [ln.rstrip() for ln in text.splitlines()]


def norm(s):
    return re.sub(r"\s+", " ", s.strip().lower())


def strip_numbering(s):
    """Снимает нумерацию и оформление заголовка, оставляя его текст:
    «2. Структура» / «2.1 Структура» / «## Структура» / «**Структура**»
    -> «Структура». Плоские заголовки и строки-данные не меняются:
    «2024 Команда», «2G, 3G», «SELECT *», «FIELD_*» остаются как есть."""
    s = s.strip()
    s = re.sub(r"^#{1,6}\s+", "", s)               # markdown-заголовок «## » (нужен пробел)
    # ПАРНЫЙ жирный/курсив «**…**»: одинаковое число звёзд с обоих краёв,
    # и внутренний текст не примыкает к звёздам (иначе «***X**» калечится).
    m = re.match(r"^(\*{1,3})([^*].*?[^*]|[^*])\1$", s)
    if m:
        s = m.group(2).strip()
    # нумерация: составная «2.1» / «2.1.3» ИЛИ одиночная с разделителем «2.» / «2)».
    # Число без разделителя («2024 …») намеренно НЕ снимается.
    s = re.sub(r"^\d+(?:[.)]\d+)+[.)]?\s+", "", s)
    s = re.sub(r"^\d+[.)]\s+", "", s)
    return s.strip()


def find_sections(text, cfg):
    """
    Ищет разделы шаблона по названию и синонимам.

    Возвращает (найденные, отсутствующие, помеченные_неприменимыми).
    Раздел считается найденным, если его название или синоним стоит
    отдельной строкой либо открывает строку таблицы требований.
    """
    raw = lines_of(text)
    heads = {norm(strip_numbering(ln)) for ln in raw if ln.strip()}
    # названия могут быть и первой ячейкой строки таблицы: «Часовой пояс | UTC»
    cells = set()
    for ln in raw:
        if "|" in ln:
            cells.add(norm(strip_numbering(ln.split("|")[0])))
    haystack = heads | cells

    # Словесные пометки ищем подстрокой, прочерк — только как всё
    # содержимое: иначе «PROVIDER_GEO — платформа агрегации» читается
    # как пометка «не применимо» и раздел молча признаётся заполненным.
    na_text = {norm(m) for m in cfg["not_applicable_markers"] if len(m) > 2}
    na_exact = {norm(m) for m in cfg["not_applicable_markers"] if len(m) <= 2}
    found, missing, marked = [], [], []

    for sec in cfg["sections"]:
        if not sec.get("required", True):
            continue
        hit = None
        for alias in sec["aliases"]:
            a = norm(alias)
            if a in haystack:
                hit = alias
                break
            # раздел как префикс строки: «Глубина данных: С 01.05.2023»
            for ln in raw:
                if norm(ln).startswith(a + " ") or norm(ln).startswith(a + ":"):
                    hit = alias
                    break
            if hit:
                break

        if not hit:
            missing.append(sec["name"])
            continue

        # раздел есть — но не помечен ли он неприменимым
        idx = next((i for i, ln in enumerate(raw)
                    if norm(strip_numbering(ln)).startswith(norm(hit))), None)
        tail = ""
        if idx is not None:
            head_line = raw[idx]
            after = head_line.split(":", 1)[1] if ":" in head_line else ""
            if "|" in head_line:
                after = head_line.split("|", 1)[1]
            nxt = raw[idx + 1] if idx + 1 < len(raw) else ""
            tail = after.strip() or nxt.strip()

        t = norm(tail)
        if any(m in t for m in na_text) or t in na_exact:
            marked.append(sec["name"])
        else:
            found.append(sec["name"])

    return found, missing, marked


def check_sections(text, cfg):
    found, missing, marked = find_sections(text, cfg)
    if not missing:
        return []

    first = next((ln for ln in lines_of(text) if ln.strip()), text[:60])
    return [{
        "quote": first,
        "defect_id": "TEMPLATE_SECTION_MISSING",
        "explanation": (
            f"Относительно шаблона документации отсутствует обязательных "
            f"разделов: {len(missing)}. По правилу компании отсутствующий "
            f"раздел не удаляется, а помечается «не применимо». "
            f"Отсутствуют: {', '.join(missing)}."),
        "suggestion": (
            "Добавить перечисленные разделы либо оставить их с пометкой "
            "«не применимо», если этап обработки не выполняется."),
        "severity": "high",
        "detail": missing,
    }]


def check_nullability(text, cfg):
    conf = cfg["nullability"]
    row_re = re.compile(conf["field_row"])
    markers = [m.lower() for m in conf["markers"]]
    table_markers = [m.lower() for m in conf.get("table_markers", [])]
    table_requires = conf.get("table_requires", "").lower()
    col_marker = conf.get("column_marker", "").lower()
    bad = []

    # Проверяем ТОЛЬКО таблицу витрины/приёмника (её открывает подзаголовок
    # «Приемники…»). Таблицу источников (нет колонки обязательности по шаблону)
    # и списки полей в «Пример данных» не трогаем. Признак обязательности ищем
    # в КОНКРЕТНОЙ ячейке (по индексу колонки), а не во всей строке — иначе
    # слово в описании замаскировало бы пустую ячейку. Если колонка удалена
    # целиком — это тоже дефект (у полей нет признака обязательности).
    in_table, header_seen, col_idx = False, False, None
    for ln in lines_of(text):
        low, stripped = ln.lower(), ln.strip()
        if ("|" not in ln and any(t in low for t in table_markers)
                and (not table_requires or table_requires in low)):
            in_table, header_seen, col_idx = True, False, None
            continue
        if not in_table:
            continue
        if not stripped or "|" not in ln:      # таблица кончилась
            in_table = False
            continue
        if not header_seen:                    # строка-заголовок колонок
            cells = [c.strip().lower() for c in ln.split("|")]
            col_idx = next((k for k, c in enumerate(cells) if col_marker in c), None)
            header_seen = True
            if col_idx is None:                # колонка обязательности отсутствует
                bad.append(stripped)
            continue
        if not row_re.search(ln):
            continue
        cells = [c.strip() for c in ln.split("|")]
        cell = cells[col_idx].lower() if (col_idx is not None
                                          and col_idx < len(cells)) else ""
        if not any(m in cell for m in markers):
            bad.append(stripped)

    if not bad:
        return []

    return [{
        "quote": bad[0],
        "defect_id": "NULLABILITY_UNSPECIFIED",
        "explanation": (
            f"Для полей структуры данных не указан признак обязательности "
            f"(NOT NULL / NULLABLE). Требование кейсодателя: признак "
            f"указывается явно для каждого поля витрины. "
            f"Полей без признака: {len(bad)}."),
        "suggestion": "Добавить колонку с признаком обязательности для каждого поля.",
        "severity": "medium",
        "detail": bad,
    }]


def check_placeholders(text, cfg):
    out = []
    for ln in lines_of(text):
        for p in cfg["placeholders"]:
            if re.search(p["pattern"], ln, flags=re.IGNORECASE | re.MULTILINE):
                out.append({
                    "quote": ln.strip(),
                    "defect_id": "PLACEHOLDER_LEFT",
                    "explanation": (
                        f"В документе осталась заглушка вместо значения: "
                        f"не указано {p['what']}. Обезличенные имена вида "
                        f"TABLE_*, FIELD_*, USER_* заглушками не считаются, "
                        f"здесь другой случай."),
                    "suggestion": f"Заменить заглушку на реальное значение: {p['what']}.",
                    "severity": "medium",
                })
                break
    return out


def check_data_catalog(text, cfg):
    """Раздел Data Catalog есть, но прямой ссылки (URL) внутри него нет.
    Требование кейсодателя №2. Если раздела нет вовсе — это TEMPLATE_SECTION_MISSING,
    здесь не флагуем."""
    conf = cfg["data_catalog"]
    markers = [m.lower() for m in conf["markers"]]
    link_re = re.compile(conf.get("link_pattern", r"https?://"), re.IGNORECASE)
    lines = lines_of(text)
    header_idx = None
    for i, ln in enumerate(lines):
        if norm(strip_numbering(ln)) in markers and is_section_header(ln, cfg):
            header_idx = i
            break
    if header_idx is None:
        return []                              # раздела нет — не наш случай
    body = []
    for ln in lines[header_idx + 1:]:
        if is_section_header(ln, cfg):
            break                              # следующий раздел — конец тела
        body.append(ln)
    if any(link_re.search(b) for b in body):
        return []                              # прямая ссылка (URL) есть — норма
    # URL нет — флагуем ВСЕГДА (без ложных пропусков), но severity по наполнению.
    if any(b.strip() for b in body):
        # раздел с содержанием: на реальном DOCX ссылка могла быть гиперлинком,
        # потерянным при конвертации → мягкое «требует уточнения», не ложное high.
        return [{
            "quote": lines[header_idx].strip(),
            "defect_id": "DATA_CATALOG_MISSING",
            "explanation": (
                "В разделе Data Catalog не видно прямой ссылки (URL) на "
                "Дата-каталог. На реальном документе ссылка может быть "
                "гиперссылкой, потерянной при конвертации в текст — стоит "
                "проверить. Требование кейсодателя №2."),
            "suggestion": "Проверить/добавить прямую ссылку на Дата-каталог.",
            "severity": "clarification",
        }]
    return [{                                  # раздел пустой — ссылки точно нет
        "quote": lines[header_idx].strip(),
        "defect_id": "DATA_CATALOG_MISSING",
        "explanation": (
            "Раздел Data Catalog присутствует, но пуст — ссылки на Дата-каталог "
            "нет. Требование кейсодателя №2: привязка к источникам оформляется "
            "ссылкой на Дата-каталог."),
        "suggestion": "Добавить в раздел прямую ссылку на Дата-каталог.",
        "severity": "high",
    }]


def is_section_header(ln, cfg):
    """Строка — заголовок раздела шаблона: её содержимое ЦЕЛИКОМ (без нумерации)
    совпадает с названием раздела или синонимом. Без startswith: иначе
    content-строка «Структура HDFS: /data/x» ложно считалась бы заголовком
    раздела «Структура» и дефект бы пропал."""
    n = norm(strip_numbering(ln))
    for sec in cfg["sections"]:
        for cand in [sec["name"]] + sec.get("aliases", []):
            if n == norm(cand):
                return True
    return False


def check_hdfs(text, cfg):
    trig = re.compile(cfg["hdfs"]["trigger"], flags=re.IGNORECASE)
    fmts = [m.lower() for m in cfg["hdfs"]["format_markers"]]
    out = []

    for ln in lines_of(text):
        if not trig.search(ln):
            continue
        # заголовок раздела «Формирование ключа (kafka) / партиции (hdfs)» —
        # не объявление пути; любая другая строка с HDFS без формата — дефект
        if is_section_header(ln, cfg):
            continue
        if any(f in ln.lower() for f in fmts):
            continue
        out.append({
            "quote": ln.strip(),
            "defect_id": "HDFS_PATH_INCOMPLETE",
            "explanation": (
                "Упомянуто файловое хранилище HDFS, но не указан формат "
                "хранения. Требование кейсодателя: для файловых хранилищ "
                "прописывается полный путь в HDFS с указанием формата."),
            "suggestion": "Указать полный путь в HDFS и формат хранения (ORC, Parquet).",
            "severity": "medium",
        })
    return out


def check_vague_wording(text, cfg):
    """Добор покрытия по Femmer smells: лазейки и незакрытые перечни. Только
    FP-безопасные словари (см. template.yaml). Одно замечание на документ со
    списком, чтобы не разрывать бюджет; severity low — режется бюджетом первым."""
    conf = cfg.get("vague_wording")
    if not conf:
        return []
    cats = conf.get("categories", {})
    hits = []
    for ln in lines_of(text):
        low = ln.lower()
        for cat, phrases in cats.items():
            hit = next((p for p in phrases if p.lower() in low), None)
            if hit:
                hits.append((ln.strip(), cat, hit))
                break
    if not hits:
        return []
    phrases = sorted({"«%s»" % h[2] for h in hits})
    return [{
        "quote": hits[0][0],
        "defect_id": "VAGUE_WORDING",
        "explanation": (
            "Расплывчатые формулировки снижают проверяемость требований "
            "(лазейки или незакрытые перечни). Найдено: %d. Примеры: %s."
            % (len(hits), ", ".join(phrases))),
        "suggestion": "Заменить на конкретное измеримое условие или полный перечень.",
        "severity": "low",
        "detail": ["%s: %s" % (h[1], h[0]) for h in hits],
    }]


def check_no_filter(text, cfg):
    """Шаг фильтрации с заголовком, но без содержания и без пометки «не применимо».
    Требование кейсодателя №4 (типовые фильтры). Детерминированно."""
    conf = cfg.get("filter_step")
    if not conf:
        return []
    step_re = re.compile(conf["heading"], re.IGNORECASE)
    marker = conf.get("marker", "фильтр").lower()
    na = [m.lower() for m in cfg.get("not_applicable_markers", []) if len(m) > 2]
    lines = lines_of(text)
    for i, ln in enumerate(lines):
        if not step_re.search(ln) or marker not in ln.lower():
            continue
        content = []
        for nxt in lines[i + 1:]:
            if step_re.search(nxt) or is_section_header(nxt, cfg):
                break                      # конец шага — следующий шаг/раздел
            if nxt.strip():                # пустые строки пропускаем, не обрываемся
                content.append(nxt.strip())
        blob = (" ".join(content) + " " + ln).lower()
        # содержание есть и это не только пометка «не применимо»
        real = [c for c in content if not any(m in c.lower() for m in na)]
        if real:
            continue                       # шаг описан — не дефект, ищем дальше
        if any(m in blob for m in na):
            continue                       # помечено «не применимо» — норма
        return [{
            "quote": ln.strip(),
            "defect_id": "NO_FILTER_DESCRIPTION",
            "explanation": (
                "Шаг фильтрации указан заголовком, но не описан и не помечен "
                "«не применимо». Требование кейсодателя №4: типовые фильтры "
                "должны быть описаны."),
            "suggestion": "Описать применяемые фильтры либо пометить шаг «не применимо».",
            "severity": "high",
        }]
    return []


def check_serialization(text, cfg):
    """В таблице «Источники данных» колонка «Сериализация» пуста для источника.
    Требование кейсодателя №1. Детерминированно: scope на таблицу источников,
    парсинг колонки сериализации по заголовку, проверка ячейки."""
    conf = cfg.get("serialization")
    if not conf:
        return []
    sec_markers = [m.lower() for m in conf["section_markers"]]
    header_markers = [m.lower() for m in conf.get("header_markers", [])]
    col_marker = conf["column_marker"].lower()
    empty = [m.lower() for m in conf.get("empty_markers", ["—", "-"])]
    lines = lines_of(text)
    in_table, col_idx, header_seen = False, None, False
    bad = []
    for ln in lines:
        low = ln.lower()
        if "|" not in ln and norm(strip_numbering(ln)) in sec_markers \
                and is_section_header(ln, cfg):
            in_table, col_idx, header_seen = True, None, False
            continue
        if not in_table:
            continue
        if "|" not in ln:
            if is_section_header(ln, cfg):     # следующий раздел — конец таблицы
                in_table = False
            continue                            # пустые строки пропускаем
        if not header_seen:
            cells = [c.strip().lower() for c in ln.split("|")]
            if not any(h in low for h in header_markers):
                continue                        # не строка-заголовок таблицы
            col_idx = next((k for k, c in enumerate(cells) if col_marker in c), None)
            header_seen = True
            continue
        if col_idx is None:
            continue                            # колонки сериализации нет — не проверяем
        cells = [c.strip() for c in ln.split("|")]
        cell = cells[col_idx].strip().lower() if col_idx < len(cells) else ""
        if not cell or cell in empty:
            bad.append(ln.strip())
    if not bad:
        return []
    return [{
        "quote": bad[0],
        "defect_id": "SERIALIZATION_UNSPECIFIED",
        "explanation": (
            "Для источника в таблице «Источники данных» не указана сериализация "
            "(формат/схема/способ десериализации). Требование кейсодателя №1: "
            "сериализация входного потока должна быть задана. Источников без "
            "сериализации: %d." % len(bad)),
        "suggestion": "Указать сериализацию (формат/схему) для каждого источника.",
        "severity": "high",
        "detail": bad,
    }]


def check_timezone(text, cfg):
    """Поле «Часовой пояс» заполнено, но конкретный пояс не назван.

    Детерминированно: метка поля стоит в начале строки, значение берётся
    после «:» или «|» (если строка обрывается — следующая непустая строка),
    и в значении ищется хотя бы одно конкретное обозначение пояса
    (UTC / GMT / МСК / смещение / IANA). Ни одного — замечание.
    Значение вида «Местное время региона» границы периода не задаёт.

    Второй случай — пояс назван, но разделы трактуют его по-разному —
    выделен в отдельный тип TIMEZONE_INCONSISTENT: он кросс-фрагментный
    и остаётся за моделью (defects_prompt.yaml, GLOBAL_TYPES)."""
    conf = cfg.get("timezone")
    if not conf:
        return []
    label_re = re.compile(conf["label_pattern"], re.I)
    zone_res = [re.compile(p, re.I) for p in conf["zone_patterns"]]
    lines = lines_of(text)
    bad = []
    for i, ln in enumerate(lines):
        if ":" not in ln and "|" not in ln:
            continue
        sep = min([p for p in (ln.find(":"), ln.find("|")) if p >= 0])
        label = norm(strip_numbering(ln[:sep]))
        if not label_re.match(label):
            continue
        value = ln[sep + 1:].strip(" |")
        if not value:                       # значение перенесено на следующую строку
            value = next((n.strip() for n in lines[i + 1:] if n.strip()), "")
        if any(r.search(value) for r in zone_res):
            continue
        bad.append(ln.strip())
    if not bad:
        return []
    return [{
        "quote": bad[0],
        "defect_id": "TIMEZONE_UNDEFINED",
        "explanation": (
            "В поле «Часовой пояс» не назван конкретный пояс (UTC, смещение "
            "или зона IANA). Границы периода в правилах фильтрации становятся "
            "нетрактуемыми: разные источники сдвинут их по-разному."),
        "suggestion": ("Указать конкретный часовой пояс (например, UTC) и поле, "
                       "несущее метку смещения."),
        "severity": "high",
        "detail": bad,
    }]


CHECKS = [check_sections, check_nullability, check_placeholders,
          check_data_catalog, check_hdfs, check_vague_wording, check_no_filter,
          check_serialization, check_timezone]


def run(text, cfg):
    findings = []
    for fn in CHECKS:
        findings.extend(fn(text, cfg))

    findings.sort(key=lambda f: {"high": 0, "medium": 1, "low": 2}.get(
        f.get("severity", "medium"), 1))

    return {
        "mode": "formal",
        "fragments": 1,
        "total_seconds": 0.0,
        "found_raw": len(findings),
        "verified": len(findings),
        "rejected_count": 0,
        "reject_reasons": {},
        "findings": findings,
        "rejected": [],
    }


def verify_quotes(res, text):
    """Цитата обязана дословно встречаться в документе. Проверка своя же,
    но без неё отчёт может сослаться на строку, которой нет."""
    bad = [f["quote"] for f in res["findings"] if f["quote"] not in text]
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc", required=True)
    ap.add_argument("--template", default="template.yaml")
    ap.add_argument("--out", default="results")
    args = ap.parse_args()

    text = Path(args.doc).read_text(encoding="utf-8")
    cfg = load_config(args.template)

    _, missing, marked = find_sections(text, cfg)
    res = run(text, cfg)

    bad = verify_quotes(res, text)
    if bad:
        print(f"  !! цитат не найдено в документе: {len(bad)}")

    outdir = Path(args.out)
    outdir.mkdir(exist_ok=True)
    path = outdir / f"{Path(args.doc).stem}_formal.json"
    path.write_text(json.dumps(res, ensure_ascii=False, indent=2),
                    encoding="utf-8")

    print(f"\n=== formal: {args.doc} ===")
    print(f"  замечаний:            {len(res['findings'])}")
    print(f"  разделов отсутствует: {len(missing)}")
    print(f"  помечено «не применимо»: {len(marked)}")
    for f in res["findings"]:
        n = len(f.get("detail", [])) or ""
        print(f"    {f['defect_id']:26s} {n}")
    print(f"  сохранено: {path}")


if __name__ == "__main__":
    main()
