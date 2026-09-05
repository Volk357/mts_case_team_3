#!/usr/bin/env python3
"""
Генератор синтетических ТЗ с заранее известными дефектами.

Порядок работы:
  1. Собрать чистый документ по шаблону кейсодателя (детерминированно).
  2. Применить план мутаций. Каждая портит документ известным способом
     в известном месте и записывает запись эталона.
  3. Отрендерить документ ОДИН раз после всех мутаций.
  4. Разрешить якоря и контейнеры, проверить инварианты по классам.

Запуск:
    python generate.py --out data/synth
"""

import argparse
import json
import os
import sys

from domains import DOMAINS, NA_SECTIONS, build_clean
from mutators import (RECIPES, apply_entry, targets_of,
                      PRESENCE, ABSENCE, SECTION_REMOVED)

PLANS = [
    ("synth_1", "traffic", [
        "DANGLING_SECTION_REFERENCE", "INTERNAL_CONTRADICTION", "UNDEFINED_EDGE_CASE",
        "AMBIGUOUS_LOGIC", "UNSPECIFIED_FORMAT", "DUPLICATE_SEMANTICS",
        "SCHEMA_TYPE_MISMATCH", "MISSING_SOURCE_LOCATION", "PLACEHOLDER_LEFT",
        "FILTER_RESULT_UNDEFINED", "NO_VOLUME_ESTIMATE", "TIMEZONE_UNDEFINED",
        "SERIALIZATION_UNSPECIFIED", "REFERENCE_LIST_MISSING",
        "NULLABILITY_UNSPECIFIED", "TEMPLATE_SECTION_MISSING_FAQ",
    ]),
    ("synth_2", "radio", [
        "INCOMPLETE_SCHEMA", "NO_FILTER_DESCRIPTION", "NO_DEDUP_OR_KEY",
        "NO_SCHEDULE", "RETENTION_GAP", "TIMEZONE_UNDEFINED",
        "SCHEMA_TYPE_MISMATCH", "DATA_CATALOG_MISSING", "HDFS_PATH_INCOMPLETE",
        "TEMPLATE_SECTION_MISSING_DDL", "PLACEHOLDER_LEFT_JIRA",
        "TEXT_STRUCTURE_ERROR", "DANGLING_SECTION_REFERENCE", "AMBIGUOUS_LOGIC",
    ]),
    ("synth_3", "churn", [
        "UNDEFINED_EDGE_CASE", "NO_VOLUME_ESTIMATE",
        "SERIALIZATION_UNSPECIFIED", "TEXT_STRUCTURE_ERROR",
    ]),
    ("synth_4", "roaming", [
        "DANGLING_SECTION_REFERENCE", "INTERNAL_CONTRADICTION", "UNDEFINED_EDGE_CASE",
        "AMBIGUOUS_LOGIC", "UNSPECIFIED_FORMAT", "DUPLICATE_SEMANTICS",
        "PII_NO_PROTECTION", "MISSING_SOURCE_LOCATION", "PLACEHOLDER_LEFT",
        "FILTER_RESULT_UNDEFINED", "NO_DEDUP_OR_KEY", "NO_SCHEDULE",
        "RETENTION_GAP", "NULLABILITY_UNSPECIFIED", "REFERENCE_LIST_MISSING",
        "DATA_CATALOG_MISSING", "TEMPLATE_SECTION_MISSING_FAQ",
    ]),
    ("synth_5", "services", [
        "INCOMPLETE_SCHEMA", "NO_FILTER_DESCRIPTION", "TIMEZONE_UNDEFINED",
        "PII_NO_PROTECTION", "HDFS_PATH_INCOMPLETE",
        "TEMPLATE_SECTION_MISSING_DDL", "INTERNAL_CONTRADICTION",
        "NO_VOLUME_ESTIMATE", "NO_SCHEDULE", "RETENTION_GAP",
        "SERIALIZATION_UNSPECIFIED", "REFERENCE_LIST_MISSING",
        "TEXT_STRUCTURE_ERROR", "PLACEHOLDER_LEFT_JIRA",
    ]),
]

SECTION_TITLES = {
    "common": "Общие сведения", "problem": "Решаемая проблема",
    "metrics": "Продуктовые метрики", "customers": "Заказчики",
    "nfr": "Нефункциональные требования", "srcsystems": "Системы-источники",
    "catalog": "Data Catalog", "repo": "Исходники проекта", "team": "Команда",
    "jira": "JIRA", "sources": "Источники данных",
    "enrich": "Источники обогащения данных", "receivers": "Приемники данных",
    "scheme": "Схема потоков данных", "algo": "Алгоритм обработки потока",
    "key": "Формирование ключа (kafka) / партиции (hdfs)",
    "struct": "Структура данных", "sample": "Пример данных", "ddl": "DDL",
    "faq": "FAQ", "history": "История изменений", "mut": "Общие сведения",
}


def section_of(nid):
    return SECTION_TITLES.get(nid.split(".")[0], "—")


def container_of(doc, nid):
    """Ближайший шаг или раздел, содержащий узел. Он переживёт удаление."""
    node = doc.find(nid)
    cur = node.parent
    while cur is not None and cur.kind not in ("step", "section"):
        cur = cur.parent
    if cur is None:
        raise ValueError("нет контейнера для " + nid)
    return cur.id


def lines_of(text):
    return [x.strip() for x in text.split("\n") if x.strip()]


def build_one(doc_id, domain_key, recipe_names):
    domain = DOMAINS[domain_key]
    problems = []

    clean_text = build_clean(domain_key, doc_id).render()
    doc = build_clean(domain_key, doc_id)

    entries = []
    for name in recipe_names:
        recipe = RECIPES.get(name)
        if recipe is None:
            problems.append(doc_id + ": неизвестный рецепт " + name)
            continue
        e = recipe(domain)
        if e is None:
            problems.append(doc_id + ": рецепт " + name +
                            " неприменим к домену " + domain_key)
            continue
        e["_recipe"] = name
        entries.append(e)

    tg = []
    for e in entries:
        tg.extend(targets_of(e))
    dup = sorted({t for t in tg if tg.count(t) > 1})
    if dup:
        problems.append(doc_id + ": несколько мутаций в один узел: " + str(dup))

    # Контейнеры и вырезанный текст фиксируются ДО применения мутаций.
    for e in entries:
        cls = e["defect_class"]
        if cls == ABSENCE:
            try:
                e["_containers"] = ([container_of(doc, targets_of(e)[0])]
                                    + list(e.get("extra_containers", [])))
            except (KeyError, ValueError) as err:
                problems.append(doc_id + ": контейнер не найден для "
                                + e["_recipe"] + ": " + str(err))
                e["_containers"] = []
        elif cls == SECTION_REMOVED:
            try:
                e["_section_title"] = doc.find(e["target"]).title
            except KeyError:
                problems.append(doc_id + ": раздел " + e["target"] + " не найден")
                e["_section_title"] = ""

        if e["op"] in ("delete", "delete_many"):
            removed = []
            for t in targets_of(e):
                try:
                    n = doc.find(t)
                except KeyError:
                    continue
                txt = n.text or " ".join(getattr(n, "cells", []))
                if not txt and n.children:
                    txt = " / ".join(
                        (c.text or " ".join(getattr(c, "cells", [])))
                        for c in n.children)
                if txt:
                    removed.append(txt)
            if removed:
                e["_removed"] = " ".join(removed)[:400]

    for e in entries:
        try:
            apply_entry(doc, e)
        except KeyError as err:
            problems.append(doc_id + ": мутация " + e["_recipe"]
                            + " не нашла узел " + str(err))

    dirty_text = doc.render()

    # Якоря presence не должны совпадать: иначе эталон неоднозначен.
    anchors = [e["anchor"] for e in entries if e["defect_class"] == PRESENCE]
    dup_a = sorted({a for a in anchors if anchors.count(a) > 1})
    if dup_a:
        problems.append(doc_id + ": повторяющиеся якоря presence: " + str(dup_a))

    defects = []
    for e in entries:
        cls = e["defect_class"]
        rec = {
            "defect_id": e["defect_id"],
            "defect_class": cls,
            "mutation": e["mutation"],
            "note": e["note"],
            "detectable_by": e["detectable_by"],
        }
        if "_removed" in e:
            rec["removed_text"] = e["_removed"]

        if cls == PRESENCE:
            try:
                q = doc.text_of(e["anchor"])
            except KeyError:
                problems.append(doc_id + ": якорь " + e["anchor"]
                                + " рецепта " + e["_recipe"]
                                + " не пережил мутации")
                continue
            if "\n" in q:
                head = q.split("\n", 1)[0].strip()
                if head and dirty_text.count(head) == 1:
                    rec["quote_full_block"] = q
                    q = head
            rec["quote"] = q
            rec["section"] = section_of(e["anchor"])
            rec["anchor_node"] = e["anchor"]

        elif cls == ABSENCE:
            containers, cl = [], []
            for cid in e["_containers"]:
                try:
                    block = doc.text_of(cid)
                except KeyError:
                    problems.append(doc_id + ": контейнер " + cid
                                    + " рецепта " + e["_recipe"]
                                    + " не пережил мутации")
                    continue
                ls = lines_of(block)
                if not ls:
                    continue
                containers.append({"node": cid, "title": ls[0], "lines": ls})
                cl.extend(ls)
            if not containers:
                problems.append(doc_id + ": у " + e["_recipe"]
                                + " не осталось ни одного контейнера")
                continue
            rec["containers"] = containers
            rec["container_lines"] = cl
            rec["quote"] = containers[0]["title"]
            rec["section"] = section_of(containers[0]["node"])

        elif cls == SECTION_REMOVED:
            rec["section_name"] = e["_section_title"]
            rec["quote"] = e["_section_title"]
            rec["section"] = e["_section_title"]
            try:
                rec["neighbor"] = lines_of(doc.text_of(e["anchor"]))[0]
            except (KeyError, IndexError):
                rec["neighbor"] = ""
        else:
            problems.append(doc_id + ": неизвестный класс " + str(cls))
            continue

        defects.append(rec)

    by_class = {}
    for d in defects:
        by_class[d["defect_class"]] = by_class.get(d["defect_class"], 0) + 1

    truth = {
        "doc": doc_id,
        "domain": domain_key,
        "clean_source": doc_id + "_clean.txt",
        "template": "Потоковые данные/витрины",
        "sections_marked_na": NA_SECTIONS.get(domain_key, []),
        "defect_count": len(defects),
        "by_class": by_class,
        "defects": defects,
    }
    return clean_text, dirty_text, truth, problems


def check_invariants(dirty_text, truth):
    """
    presence        — цитата дословна и однозначна.
    absence         — все строки контейнера присутствуют в документе.
    section_removed — имя раздела в документе отсутствует.
    """
    problems = []
    tag = truth["doc"]
    for d in truth["defects"]:
        cls, did = d["defect_class"], d["defect_id"]
        if cls == "presence":
            q = d["quote"]
            n = dirty_text.count(q)
            if not q.strip():
                problems.append(tag + " / " + did + ": пустая цитата")
            elif n == 0:
                problems.append(tag + " / " + did + ": цитата не найдена: "
                                + repr(q[:70]))
            elif n > 1:
                problems.append(tag + " / " + did + ": цитата встречается "
                                + str(n) + " раз: " + repr(q[:70]))
        elif cls == "absence":
            for ln in d["container_lines"]:
                if ln not in dirty_text:
                    problems.append(tag + " / " + did
                                    + ": строка контейнера не найдена: "
                                    + repr(ln[:70]))
                    break
        elif cls == "section_removed":
            name = d["section_name"]
            if not name:
                problems.append(tag + " / " + did + ": пустое имя раздела")
            elif name in dirty_text:
                problems.append(tag + " / " + did + ": раздел «" + name
                                + "» всё ещё присутствует в документе")
    return problems


def check_coverage(truths):
    counts = {}
    for t in truths:
        for d in t["defects"]:
            counts[d["defect_id"]] = counts.get(d["defect_id"], 0) + 1
    bad = [("тип " + k + " встречается " + str(v)
            + " раз, нужно не менее двух")
           for k, v in sorted(counts.items()) if v < 2]
    return bad, counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/synth")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    all_problems, truths = [], []

    for doc_id, domain_key, recipes in PLANS:
        clean, dirty, truth, problems = build_one(doc_id, domain_key, recipes)
        problems += check_invariants(dirty, truth)
        all_problems += problems
        truths.append(truth)

        open(args.out + "/" + doc_id + ".txt", "w",
             encoding="utf-8").write(dirty)
        open(args.out + "/" + doc_id + "_clean.txt", "w",
             encoding="utf-8").write(clean)
        json.dump(truth, open(args.out + "/" + doc_id + "_truth.json", "w",
                              encoding="utf-8"), ensure_ascii=False, indent=2)

        bc = truth["by_class"]
        det = sum(1 for d in truth["defects"]
                  if d["detectable_by"] == "deterministic")
        print("%-9s %-9s дефектов: %2d  (наличие %d, отсутствие %d, "
              "раздел удалён %d | llm %d, детерм. %d)"
              % (doc_id, domain_key, truth["defect_count"],
                 bc.get("presence", 0), bc.get("absence", 0),
                 bc.get("section_removed", 0),
                 truth["defect_count"] - det, det))

    cov, counts = check_coverage(truths)
    all_problems += cov

    total = sum(t["defect_count"] for t in truths)
    cls_totals = {}
    for t in truths:
        for k, v in t["by_class"].items():
            cls_totals[k] = cls_totals.get(k, 0) + v

    manifest = {
        "documents": [{"doc": t["doc"], "domain": t["domain"],
                       "defects": t["defect_count"],
                       "by_class": t["by_class"]} for t in truths],
        "total_defects": total,
        "by_class": cls_totals,
        "by_type": dict(sorted(counts.items())),
        "invariants_ok": not all_problems,
    }
    json.dump(manifest, open(args.out + "/synth_manifest.json", "w",
                             encoding="utf-8"), ensure_ascii=False, indent=2)

    print("\nвсего дефектов: %d, типов: %d" % (total, len(counts)))
    print("по классам: " + ", ".join(k + " " + str(v)
                                     for k, v in sorted(cls_totals.items())))

    if all_problems:
        print("\nПРОБЛЕМЫ:")
        for p in all_problems:
            print(" -", p)
        sys.exit(1)

    print("инварианты выполнены")


if __name__ == "__main__":
    main()
