#!/usr/bin/env python3
"""Проверка синтетического эталона на fault masking (пункт 2 очереди).

Вопрос: не является ли часть дефектов принципиально ненаходимой из-за того,
что одна мутация стирает доказательство, на котором держится другая
(fault masking / mutant interference)? Такие дефекты надо исключить из
знаменателя recall, иначе он несправедлив к инструменту.

Критерий masked — ЧИСТО СТРУКТУРНЫЙ и независимый от результата инструмента
(мутант либо находим, либо нет — это свойство эталона, а не прогона). masked
применяется только к КОМПАРАТИВНЫМ типам: дефект которых ПО ОПРЕДЕЛЕНИЮ требует
двух сторон, и удаление одной делает его нераспознаваемым в принципе.

  SCHEMA_INCONSISTENCY   расхождение типов между источником и витриной. Якорь
                         struct.src.<поле>, обязательная вторая сторона
                         struct.recv.<поле>. INCOMPLETE_SCHEMA удаляет struct.recv
                         → сравнивать не с чем → masked.
  INTERNAL_CONTRADICTION два противоречащих утверждения. Вторая сторона —
                         исходное утверждение о способе загрузки (common.load).
                         В планах не удаляется → на деле не masked.

Одно-локационные типы (TEXT_STRUCTURE_ERROR, TIMEZONE_UNDEFINED, DUPLICATE_SEMANTICS
и пр.) НЕ считаются masked, даже если соседняя мутация стирает поддерживающий
контекст: дефект остаётся в одном месте, сигнал имени поля/строки сохраняется —
это ослабление доказательства, не его исчезновение. Проверяем это фактически:
реконструируем чистое и грязное дерево реплеем плана мутаций и смотрим, исчез ли
ОБЯЗАТЕЛЬНЫЙ узел-вторая-сторона компаративного типа.

Дополнительно считаем со-локацию (делят регион узла или раздел) как более
слабый сигнал.

Запуск: python analyze_masking.py
"""
import argparse
import json
import os

from score import match, gather
from generate import PLANS, section_of
from domains import DOMAINS, build_clean
from mutators import RECIPES, apply_entry


def build_trees(doc_id, domain_key, recipe_names):
    """Чистое и грязное дерево документа. Грязное — реплей плана мутаций,
    в точности как в generate.build_one (тот же порядок рецептов)."""
    clean = build_clean(domain_key, doc_id)
    dirty = build_clean(domain_key, doc_id)
    for name in recipe_names:
        recipe = RECIPES.get(name)
        if recipe is None:
            continue
        e = recipe(DOMAINS[domain_key])
        if e is None:
            continue
        try:
            apply_entry(dirty, e)
        except KeyError:
            pass
    return clean, dirty


def exists(tree, nid):
    try:
        tree.find(nid)
        return True
    except KeyError:
        return False


def second_side(defect):
    """Обязательный узел-вторая-сторона для КОМПАРАТИВНОГО дефекта (тип,
    существующий только как противоречие между двумя местами). Для остальных
    типов пусто — их доказательство одно-локационно и не маскируется."""
    did = defect["defect_id"]
    a = defect.get("anchor_node") or ""
    if did == "SCHEMA_INCONSISTENCY" and a.startswith("struct.src."):
        return ["struct.recv." + a.split(".", 2)[2]]
    if did == "INTERNAL_CONTRADICTION":
        return ["common.load"]
    return []


def is_masked(defect, clean, dirty):
    """Структурно, независимо от результата инструмента: обязательная вторая
    сторона была в чистом документе, но стёрта соседней мутацией из грязного."""
    for ev in second_side(defect):
        if exists(clean, ev) and not exists(dirty, ev):
            return True
    return False


def overlap(a, b):
    if not a or not b:
        return False
    return a == b or a.startswith(b + ".") or b.startswith(a + ".")


def regions_of(defect):
    """(узлы дефекта, раздел). Раздел нужен для со-локации section_removed."""
    cls = defect["defect_class"]
    if cls == "presence":
        n = defect.get("anchor_node")
        return ([n] if n else []), defect.get("section")
    if cls == "absence":
        nodes = [c["node"] for c in defect.get("containers", []) if c.get("node")]
        return nodes, defect.get("section")
    if cls == "section_removed":
        return [], defect.get("section_name")
    return [], None


def colocated(i, meta):
    ai, si = meta[i]
    for j, (aj, sj) in enumerate(meta):
        if j == i:
            continue
        if any(overlap(a, b) for a in ai for b in aj):
            return True
        # section_removed: пересечение по разделу
        if si and sj and si == sj and (not ai or not aj):
            return True
    return False


def analyze(truths_dir, res_dir, suffix):
    rows_out = []
    for doc_id, domain_key, recipe_names in PLANS:
        path = os.path.join(truths_dir, doc_id + "_truth.json")
        if not os.path.exists(path):
            continue
        truth = json.load(open(path, encoding="utf-8"))
        findings, _ = gather(res_dir, doc_id, suffix)
        rows, _ = match(truth, findings)
        clean, dirty = build_trees(doc_id, domain_key, recipe_names)
        defs = truth["defects"]
        meta = [regions_of(d) for d in defs]
        for i, d in enumerate(defs):
            rows_out.append({
                "doc": doc_id, "defect_id": d["defect_id"],
                "class": d["defect_class"], "detectable_by": d["detectable_by"],
                "found": rows[i]["found_by_place"],
                # структурно, независимо от результата инструмента
                "masked": is_masked(d, clean, dirty),
                "colocated": colocated(i, meta),
                "near_removal": _near_removal(d, defs, meta),
            })
    return rows_out


def _near_removal(d, defs, meta):
    if d["defect_class"] != "presence":
        return False
    removal_nodes, removal_sections = [], set()
    for d2, (nds2, sec2) in zip(defs, meta):
        if d2["defect_class"] == "absence":
            removal_nodes += nds2
        elif d2["defect_class"] == "section_removed" and sec2:
            removal_sections.add(sec2)
    a = (d.get("anchor_node") or "")
    in_abs = any(a == rn or a.startswith(rn + ".") for rn in removal_nodes)
    return in_abs or d.get("section") in removal_sections


def pct(num, den):
    return round(num / den * 100) if den else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", nargs=2, metavar=("SYNTH_DIR", "RESULTS_DIR"),
                    default=["data/synth", "results"])
    ap.add_argument("--suffix", default="_full2")
    args = ap.parse_args()
    rows = analyze(args.batch[0], args.batch[1], args.suffix)

    total = len(rows)
    found = sum(r["found"] for r in rows)
    masked = [r for r in rows if r["masked"]]
    findable = [r for r in rows if not r["masked"]]
    f_found = sum(r["found"] for r in findable)

    llm = [r for r in rows if r["detectable_by"] == "llm"]
    llm_find = [r for r in llm if not r["masked"]]

    near = [r for r in rows if r["near_removal"]]
    near_found = sum(r["found"] for r in near)
    coloc = sum(1 for r in rows if r["colocated"])

    print("дефектов всего: %d, найдено по месту: %d (%d%%)"
          % (total, found, pct(found, total)))
    print("со-локованных: %d, изолированных: %d" % (coloc, total - coloc))
    print("near_removal (presence в удаляемом регионе): %d, найдено %d (%d%%)"
          % (len(near), near_found, pct(near_found, len(near))))
    print()
    print("ЗАМАСКИРОВАНО (компаративный тип, обязательная вторая сторона "
          "структурно стёрта): %d" % len(masked))
    for r in masked:
        print("    %-9s %-24s found=%s" % (r["doc"], r["defect_id"], r["found"]))
    print()
    print("recall на ПОЛНОМ знаменателе:      %d/%d = %d%%"
          % (found, total, pct(found, total)))
    print("recall на НАХОДИМОМ знаменателе:   %d/%d = %d%%"
          % (f_found, len(findable), pct(f_found, len(findable))))
    print("llm-слой находимый:                %d/%d = %d%%"
          % (sum(r["found"] for r in llm_find), len(llm_find),
             pct(sum(r["found"] for r in llm_find), len(llm_find))))
    print()
    delta = pct(f_found, len(findable)) - pct(found, total)
    if len(masked) >= 5 or delta >= 5:
        print("ВЫВОД: masking заметен (%d дефектов, +%d п.п. к recall) — вывод "
              "«модель недобирает» смягчить, считать по находимому знаменателю."
              % (len(masked), delta))
    else:
        print("ВЫВОД: masking маргинален (%d дефект, знаменатель %d→%d, recall "
              "+%d п.п.). Вывод «модель недобирает» в силе; исключаем "
              "замаскированное и считаем по находимому знаменателю."
              % (len(masked), total, len(findable), delta))


if __name__ == "__main__":
    main()
