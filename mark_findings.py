#!/usr/bin/env python3
"""
Слепая оценка полезности замечаний.

Показывает замечания из обоих режимов вперемешку, не сообщая,
какое откуда. Вы отмечаете полезное / бесполезное, в конце
скрипт раскрывает раскладку и считает статистику.

Слепота важна: если знать, что замечание из taxonomy, оценка
неосознанно завышается. На защите «оценка проводилась вслепую» —
сильный аргумент.

Использование:
    python3 mark_findings.py --doc vitrina

Прерваться можно в любой момент (Ctrl+C), отметки сохраняются.
При повторном запуске продолжит с места остановки.
"""

import argparse
import hashlib
import json
import random
from pathlib import Path

HELP = """
  y — полезное: аналитик увидит это и поправит документ
  n — бесполезное: придирка, банальность или не про этот документ
  s — пропустить, вернуться позже
  q — выйти и посмотреть результаты
"""


def load_findings(results_dir, doc, modes):
    items = []
    for mode in modes:
        path = results_dir / f"{doc}_{mode}.json"
        if not path.exists():
            print(f"Нет файла {path}, пропускаю")
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for f in data["findings"]:
            # ключ по содержанию, а не по номеру: отметки переживают
            # перезапуск раннера, даже если состав замечаний изменился
            h = hashlib.md5(
                (f.get("quote", "") + f.get("explanation", "")).encode("utf-8")
            ).hexdigest()[:12]
            items.append({
                "key": f"{mode}:{h}",
                "mode": mode,
                "quote": f.get("quote", ""),
                "defect_id": f.get("defect_id", ""),
                "explanation": f.get("explanation", ""),
                "suggestion": f.get("suggestion", ""),
                "severity": f.get("severity", ""),
            })
    return items


def show(item, n, total):
    print("\n" + "=" * 70)
    print(f"Замечание {n} из {total}")
    print("=" * 70)
    print(f"\nЦИТАТА:\n  {item['quote']}")
    print(f"\nТИП: {item['defect_id']}   ВАЖНОСТЬ: {item['severity']}")
    print(f"\nПОЧЕМУ ПРОБЛЕМА:\n  {item['explanation']}")
    print(f"\nЧТО УТОЧНИТЬ:\n  {item['suggestion']}")
    print()


def report(items, marks):
    print("\n\n" + "=" * 70)
    print("РЕЗУЛЬТАТЫ")
    print("=" * 70)

    stats = {}
    for it in items:
        m = marks.get(it["key"])
        if m not in ("y", "n"):
            continue
        s = stats.setdefault(it["mode"], {"useful": 0, "useless": 0})
        s["useful" if m == "y" else "useless"] += 1

    for mode in sorted(stats):
        s = stats.get(mode)
        if not s:
            continue
        total = s["useful"] + s["useless"]
        share = f"{s['useful'] / total * 100:.0f}%" if total else "—"
        print(f"\n{mode}:")
        print(f"  оценено:     {total}")
        print(f"  полезных:    {s['useful']} ({share})")
        print(f"  бесполезных: {s['useless']}")

    if len(stats) >= 2:
        print("\n" + "-" * 70)
        print("  Доля полезных по режимам:")
        for mode in sorted(stats):
            s = stats[mode]
            tot = s["useful"] + s["useless"]
            pct = s["useful"] / tot * 100 if tot else 0
            print(f"    {mode:10s} {pct:5.0f}%   полезных {s['useful']} из {tot}")
        print("\n  Это и есть цифры для презентации.")

    # какие типы дефектов чаще оказываются бесполезными
    bad = {}
    for it in items:
        if marks.get(it["key"]) == "n":
            bad[it["defect_id"]] = bad.get(it["defect_id"], 0) + 1
    if bad:
        print("\n  Типы, чаще всего дающие бесполезные замечания:")
        for k, v in sorted(bad.items(), key=lambda x: -x[1])[:5]:
            print(f"    {k}: {v}")
        print("  Их стоит понизить в severity или уточнить формулировку.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc", required=True,
                    help="имя документа без расширения, например vitrina")
    ap.add_argument("--results", default="results")
    ap.add_argument("--modes", default="baseline,taxonomy,dict",
                    help="через запятую: какие режимы оценивать")
    args = ap.parse_args()

    results_dir = Path(args.results)
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    items = load_findings(results_dir, args.doc, modes)
    if not items:
        print("Замечаний не найдено. Сначала запустите run_review.py")
        return

    marks_path = results_dir / f"{args.doc}_marks.json"
    marks = {}
    if marks_path.exists():
        marks = json.loads(marks_path.read_text(encoding="utf-8"))
        print(f"Продолжаю: уже отмечено {len(marks)}")

    random.seed(42)
    random.shuffle(items)

    pending = [it for it in items if it["key"] not in marks]
    print(f"\nК оценке: {len(pending)} замечаний")
    print(HELP)

    try:
        for n, it in enumerate(pending, 1):
            show(it, n, len(pending))
            while True:
                a = input("  [y/n/s/q] > ").strip().lower()
                if a in ("y", "n", "s", "q"):
                    break
                print(HELP)
            if a == "q":
                break
            if a != "s":
                marks[it["key"]] = a
                marks_path.write_text(
                    json.dumps(marks, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    except KeyboardInterrupt:
        print("\n\nПрервано, отметки сохранены.")

    report(items, marks)
    print(f"\n  Отметки: {marks_path}")


if __name__ == "__main__":
    main()
