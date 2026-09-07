#!/usr/bin/env python3
"""
Обмен «полнота против точности» — offline replay зафиксированного прогона.

Слой семантической верификации выносит суждение по каждому замечанию слоя
модели. Режим задаётся политикой пакета:
  * `advisory`  — вердикт выносится и виден в результате, выдачу не меняет;
  * `enforcing` — замечания с вердиктом `reject` убираются.
Замечания слоя правил через верификатор не проходят вовсе: слой правил и есть
независимая проверка. Замечания без вердикта остаются в обоих режимах —
молчание верификатора не приговор.

Скрипт берёт один зафиксированный прогон с вердиктами и считает обе строки
таблицы одним инструментом, чтобы их можно было сравнивать.

Запуск из корня репозитория:
    python3 evidence/2026-09-07/replay_enforcing.py --out /tmp/enf
    python3 score.py --batch data/synth evidence/2026-09-07/verification-run --suffix _full2  # advisory
    python3 score.py --batch data/synth /tmp/enf --suffix _full2                              # enforcing

Ожидаемый результат (зафиксирован 7 сентября 2026):
    advisory   выдано 105 | 89% (58/65) по месту, 78% (51/65) по типу | точность 55%
    enforcing  выдано  51 | 63% (41/65) по месту, 46% (30/65) по типу | точность 80%

⚠️ Граница метода: это replay ОДНОГО прогона, модель заново не вызывается.
Разброс между прогонами для этого замера не измерялся — в отличие от полноты,
где четыре прогона дали ±1 дефект.
"""

import argparse
import glob
import json
import os
import shutil
import sys

SRC = os.path.join("evidence", "2026-09-07", "verification-run")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--src", default=SRC)
    args = ap.parse_args()

    os.makedirs(os.path.join(args.out, "formal"), exist_ok=True)
    kept = dropped = lost_real = 0

    for path in sorted(glob.glob(os.path.join(args.src, "*_full2.json"))):
        doc = os.path.basename(path).replace("_full2.json", "")
        findings = json.load(open(path, encoding="utf-8")).get("findings", [])
        keep = [f for f in findings
                if (f.get("_verdict") or {}).get("verdict") != "reject"]
        kept += len(keep)
        dropped += len(findings) - len(keep)
        json.dump({"findings": keep},
                  open(os.path.join(args.out, f"{doc}_full2.json"), "w"),
                  ensure_ascii=False)

    # Слой правил копируется как есть: верификатор его не касается.
    for path in glob.glob(os.path.join(args.src, "formal", "*_formal.json")):
        shutil.copy(path, os.path.join(args.out, "formal"))

    print(f"замечаний слоя модели: оставлено {kept}, отвергнуто {dropped}")
    print("дальше: python3 score.py --batch data/synth", args.out, "--suffix _full2")
    return 0


if __name__ == "__main__":
    sys.exit(main())
