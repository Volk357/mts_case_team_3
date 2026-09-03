#!/usr/bin/env python3
"""
Считает полноту инструмента ревью по синтетическому эталону.

Сопоставление зависит от класса дефекта — это принципиально.

  presence         испорченный текст в документе есть. Замечание должно
                   процитировать именно его. Сопоставление строгое.
  absence          содержание вырезано. Процитировать нечего, поэтому
                   попаданием считается указание на любую строку того
                   раздела или шага, где содержание должно быть.
  section_removed  раздел удалён целиком. Попаданием считается указание
                   имени раздела в цитате или в объяснении.

Полнота считается раздельно по классам и по слоям (llm против
детерминированного). Замечания детерминированного слоя подмешиваются
автоматически из RESULTS/formal.

Запуск:
    python score.py --batch data/synth results
    python score.py --truth data/synth/synth_1_truth.json \
                    --findings results/synth_1_full2.json
    python score.py --clean results/synth_1_clean_full2.json
"""

import argparse
import json
import os
import re
import sys

_WORD = re.compile(r"[a-zA-Zа-яА-ЯёЁ0-9_]+")


def tokens(s):
    return set(w.lower() for w in _WORD.findall(s or ""))


def norm(s):
    return " ".join(w.lower() for w in _WORD.findall(s or ""))


def overlap(a, b):
    """Мера пересечения двух цитат. 1.0 при вложенности."""
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return 0.0
    if na in nb or nb in na:
        return 1.0
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


def mentions(name, text):
    """Упоминание имени раздела как отдельного слова."""
    if not name or not text:
        return False
    return re.search(r"(?<![\w])" + re.escape(name.lower()) + r"(?![\w])",
                     text.lower()) is not None


def place_score(truth_defect, finding, threshold):
    """Насколько замечание указывает на место дефекта. 0..1"""
    cls = truth_defect["defect_class"]
    fq = finding.get("quote", "") or ""
    fe = finding.get("explanation", "") or ""

    if cls == "presence":
        return overlap(truth_defect["quote"], fq)

    if cls == "absence":
        best = 0.0
        for ln in truth_defect.get("container_lines", []):
            best = max(best, overlap(ln, fq))
        for c in truth_defect.get("containers", []):
            if mentions(c["title"], fq) or mentions(c["title"], fe):
                best = max(best, 1.0)
        return best

    if cls == "section_removed":
        name = truth_defect.get("section_name", "")
        if mentions(name, fq) or mentions(name, fe):
            return 1.0
        nb = truth_defect.get("neighbor", "")
        return overlap(nb, fq) if nb else 0.0

    return 0.0


def match(truth, findings, threshold=0.6):
    """
    Жадное сопоставление один к одному. При равном попадании по месту
    предпочтение отдаётся замечанию с верным типом.
    """
    used, rows = set(), []
    for d in truth["defects"]:
        best, best_place, best_rank = None, 0.0, -1.0
        for i, f in enumerate(findings):
            if i in used:
                continue
            p = place_score(d, f, threshold)
            if p <= 0:
                continue
            rank = p + (1.0 if f.get("defect_id") == d["defect_id"] else 0.0)
            if rank > best_rank:
                best, best_place, best_rank = i, p, rank
        hit = best is not None and best_place >= threshold
        f = findings[best] if hit else None
        rows.append({
            "defect_id": d["defect_id"],
            "defect_class": d["defect_class"],
            "detectable_by": d["detectable_by"],
            "quote": d.get("quote", ""),
            "found_by_place": hit,
            "found_by_type": bool(f and f.get("defect_id") == d["defect_id"]),
            "matched_defect_id": f.get("defect_id") if f else None,
            "score": round(best_place, 2),
        })
        if hit:
            used.add(best)

    # Диагностика жадного матчинга — ВТОРЫМ проходом, по финальному used.
    # Дефект не засчитан строго, но замечание, сильно на него попадающее
    # (place>=threshold), уже ЗАНЯТО другим дефектом → его забрал сосед.
    # Свободные замечания выше порога (проигравшие ранг из-за бонуса за тип)
    # НЕ считаются украденными — это не конфликт one-to-one.
    for d, r in zip(truth["defects"], rows):
        stolen = False
        if not r["found_by_place"]:
            for i, g in enumerate(findings):
                if i in used and place_score(d, g, threshold) >= threshold:
                    stolen = True
                    break
        r["stolen_by_neighbor"] = stolen

    unmatched = [f for i, f in enumerate(findings) if i not in used]
    return rows, unmatched


def _rate(rows, sel, key):
    sub = [r for r in rows if sel(r)]
    if not sub:
        return "—", 0, 0
    hit = sum(1 for r in sub if r[key])
    return "%d%%" % round(hit / len(sub) * 100), hit, len(sub)


def report(rows, unmatched, label, verbose=True):
    n_found = sum(1 for r in rows if r["found_by_place"])
    print("\n=== " + label + " ===")
    print("дефектов в эталоне: %d, замечаний инструмента: %d"
          % (len(rows), n_found + len(unmatched)))

    groups = [
        ("все", lambda r: True),
        ("наличие", lambda r: r["defect_class"] == "presence"),
        ("отсутствие", lambda r: r["defect_class"] == "absence"),
        ("раздел удалён", lambda r: r["defect_class"] == "section_removed"),
        ("слой llm", lambda r: r["detectable_by"] == "llm"),
        ("слой детерм.", lambda r: r["detectable_by"] == "deterministic"),
    ]
    for name, sel in groups:
        p, ph, pn = _rate(rows, sel, "found_by_place")
        t, th, tn = _rate(rows, sel, "found_by_type")
        print("  полнота %-13s по месту %5s (%d/%d)   и тип %5s (%d/%d)"
              % (name, p, ph, pn, t, th, tn))

    stolen = sum(1 for r in rows if r.get("stolen_by_neighbor"))
    if stolen:
        print("  из них не засчитано жадным матчингом (совпадение отдано "
              "соседу): %d" % stolen)

    if not verbose:
        return

    missed = [r for r in rows if not r["found_by_place"]]
    if missed:
        print("  пропущено:")
        for r in missed:
            mark = " *отдано соседу" if r.get("stolen_by_neighbor") else ""
            print("    - %-28s [%s] %s%s"
                  % (r["defect_id"], r["defect_class"][:8],
                     repr(r["quote"][:45]), mark))

    wrong = [r for r in rows if r["found_by_place"] and not r["found_by_type"]]
    if wrong:
        print("  место найдено, тип другой:")
        for r in wrong:
            print("    - эталон %-26s инструмент %s"
                  % (r["defect_id"], r["matched_defect_id"]))

    if unmatched:
        print("  замечаний вне эталона: %d" % len(unmatched))
        for f in unmatched:
            print("    - %-28s %s" % (f.get("defect_id", "?"),
                                      repr(str(f.get("quote", ""))[:55])))


def load_findings(path):
    data = json.load(open(path, encoding="utf-8"))
    return data["findings"] if isinstance(data, dict) else data


_DET_TYPES = None


def deterministic_types(path="defects.yaml"):
    """Множество типов, принадлежащих детерминированному слою. Кэшируется."""
    global _DET_TYPES
    if _DET_TYPES is None:
        _DET_TYPES = set()
        try:
            import yaml
            data = yaml.safe_load(open(path, encoding="utf-8"))
            _DET_TYPES = {d["id"] for d in data.get("defects", [])
                          if d.get("detectable_by") == "deterministic"}
        except Exception:
            pass
    return _DET_TYPES


def gather(res_dir, doc, suffix):
    """Замечания модели плюс замечания детерминированного слоя.

    Из модельных находок отбрасываются детерминированные типы: их авторитетный
    источник — формальный слой. Иначе модельные ложные срабатывания таких типов
    (напр. NO_FILTER_DESCRIPTION на документе с описанным фильтром) засоряют счёт.
    """
    det = deterministic_types()
    out, used = [], []
    p = os.path.join(res_dir, doc + suffix + ".json")
    if os.path.exists(p):
        out += [f for f in load_findings(p) if f.get("defect_id") not in det]
        used.append(os.path.basename(p))
    for cand in (os.path.join(res_dir, "formal", doc + "_formal.json"),
                 os.path.join(res_dir, doc + "_formal.json")):
        if os.path.exists(cand):
            out += load_findings(cand)
            used.append(os.path.basename(cand))
            break
    return out, used


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--truth")
    ap.add_argument("--findings", nargs="*")
    ap.add_argument("--batch", nargs=2, metavar=("SYNTH_DIR", "RESULTS_DIR"))
    ap.add_argument("--suffix", default="_full2",
                    help="суффикс файла замечаний модели")
    ap.add_argument("--clean")
    ap.add_argument("--threshold", type=float, default=0.6)
    args = ap.parse_args()

    if args.clean:
        f = load_findings(args.clean)
        print("негативный контроль: %d замечаний на чистом документе" % len(f))
        for x in f:
            print("  - %-28s %s" % (x.get("defect_id", "?"),
                                    repr(str(x.get("quote", ""))[:60])))
        return

    if args.batch:
        synth_dir, res_dir = args.batch
        all_rows, all_un = [], []
        for name in sorted(os.listdir(synth_dir)):
            if not name.endswith("_truth.json"):
                continue
            doc = name[:-len("_truth.json")]
            findings, used = gather(res_dir, doc, args.suffix)
            if not findings:
                print("пропуск " + doc + ": нет файлов замечаний")
                continue
            truth = json.load(open(os.path.join(synth_dir, name),
                                   encoding="utf-8"))
            rows, un = match(truth, findings, args.threshold)
            report(rows, un, doc + "  (" + ", ".join(used) + ")")
            all_rows += rows
            all_un += un
        if not all_rows:
            sys.exit("нечего считать")
        report(all_rows, all_un, "ИТОГО ПО НАБОРУ", verbose=False)
        by_type = {}
        for r in all_rows:
            a, b = by_type.get(r["defect_id"], (0, 0))
            by_type[r["defect_id"]] = (a + int(r["found_by_place"]), b + 1)
        print("\nполнота по типам (по месту):")
        for k in sorted(by_type, key=lambda k: by_type[k][0] / by_type[k][1]):
            hit, tot = by_type[k]
            print("  %-30s %d/%d" % (k, hit, tot))
        return

    if not (args.truth and args.findings):
        ap.error("нужны --truth и --findings, либо --batch, либо --clean")

    truth = json.load(open(args.truth, encoding="utf-8"))
    det = deterministic_types()
    findings = []
    for p in args.findings:
        fs = load_findings(p)
        # детерм. типы оставляем только из формального файла; из модельного
        # (как и в gather) отбрасываем — источник этих типов формальный слой
        if "_formal" not in os.path.basename(p):
            fs = [f for f in fs if f.get("defect_id") not in det]
        findings += fs
    rows, un = match(truth, findings, args.threshold)
    report(rows, un, truth["doc"])


if __name__ == "__main__":
    main()
