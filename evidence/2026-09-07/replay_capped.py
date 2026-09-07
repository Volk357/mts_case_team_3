#!/usr/bin/env python3
"""
Полнота ПОД контрактным потолком 20 — offline replay одного прогона.

Зачем. Заголовочные 89%/78% сняты на выдаче в 105 замечаний: это 21 замечание
на документ при потолке 20, то есть полнота ДО отсечения по бюджету. Здесь
к тем же артефактам применяется ТО ЖЕ правило отбора, что работает в бою
(`docreview._rank_union`), и полнота считается заново.

Честная граница метода, её надо произносить вслух: это **offline replay
зафиксированного пула кандидатов**, а не новый боевой прогон. Модель заново
не вызывается, поэтому вариативность её выдачи (±1 дефект между прогонами)
здесь не воспроизводится. Утверждать по этому замеру можно ровно одно:
на ТОМ ЖЕ пуле кандидатов отсечение по бюджету стоит 6 пунктов полноты.

Запуск из корня репозитория:
    python3 evidence/2026-09-07/replay_capped.py --out /tmp/capped
    python3 score.py --batch data/synth /tmp/capped --suffix _full2

Ожидаемый результат (зафиксирован 7 сентября 2026):
    замечаний до отсечения 105, после потолка 20 — 96
    полнота все           по месту 83% (54/65)   и тип 72% (47/65)
    полнота слой детерм.  по месту 96% (26/27)   и тип 96% (26/27)
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.getcwd())

import docreview                                             # noqa: E402
import score                                                 # noqa: E402

SRC = os.path.join("data", "ab_taxonomy", "outputs")
SUFFIX = "_newtax_full2"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="куда положить capped-артефакты")
    ap.add_argument("--src", default=SRC)
    args = ap.parse_args()

    os.makedirs(os.path.join(args.out, "formal"), exist_ok=True)
    det = score.deterministic_types()

    before = after = 0
    for i in range(1, 6):
        doc = f"synth_{i}"
        # Детерминированные типы из модельной выдачи отбрасываем — их
        # авторитетный источник формальный слой; ровно так же делает score.gather.
        model = [f for f in score.load_findings(
                    os.path.join(args.src, f"{doc}{SUFFIX}.json"))
                 if f.get("defect_id") not in det]
        formal = score.load_findings(
            os.path.join(args.src, "formal", f"{doc}_formal.json"))
        before += len(model) + len(formal)

        ranked = docreview._rank_union(formal, model)         # правило из боевого пути
        after += len(ranked)

        json.dump({"findings": [f for f, d in ranked if not d]},
                  open(os.path.join(args.out, f"{doc}_full2.json"), "w"),
                  ensure_ascii=False)
        json.dump({"findings": [f for f, d in ranked if d]},
                  open(os.path.join(args.out, "formal", f"{doc}_formal.json"), "w"),
                  ensure_ascii=False)

    print(f"замечаний до отсечения: {before}  после потолка "
          f"{docreview.BUDGET}: {after}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
