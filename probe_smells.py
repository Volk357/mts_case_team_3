#!/usr/bin/env python3
"""Воспроизводимый замер словарных кандидатов-запахов (пункт 5).

Прогоняет наивные словари Femmer/QVscribe по 5 ЧИСТЫМ синтетическим документам
(git-safe; документы кейсодателя в скрипты не коммитим — проверялись вручную,
результат тот же). Критерий добавления ДВОЙНОЙ, совпадает с taxonomy_coverage.md:
кандидат добавляется, только если (а) 0 измеренных FP на чистых И (б) у слова нет
легитимного технического омонима. Иначе — бэклог с явной причиной.

Запуск: python probe_smells.py
"""
import glob

# Каждый кандидат: (словарь-проба, есть ли легитимный омоним в тех.тексте).
CANDIDATES = {
    "loophole (Optional Escape)": (
        ["по возможности", "при необходимости", "насколько возможно",
         "как правило", "при желании", "если потребуется"], False),
    "open_ended enumeration": (
        ["и т.д", "и т. д", "и т.п", "и т. п", "и другие", "и прочие", "и так далее"], False),
    "superlatives": (["максимальн", "минимальн", "наилучш", "наибольш", "оптимальн"], True),
    "comparatives": (["быстрее", "точнее", "больше", "меньше", "выше", "ниже", "лучше"], True),
    "subjective / vague words": (["удобн", "прост", "эффективн", "гибк", "надёжн", "значительн"], True),
    "universal quantifiers": (["все ", "каждый", "всегда", "любой"], True),
    "non-specific temporal": (["регулярно", "периодически", "по мере"], True),
}


def measure(paths):
    rows = {}
    texts = [open(p, encoding="utf-8").read().lower() for p in paths]
    for name, (words, homonym) in CANDIDATES.items():
        hits, examples = 0, []
        for t in texts:
            for w in words:
                if w in t:
                    hits += 1
                    if len(examples) < 3:
                        examples.append(w.strip())
        rows[name] = (hits, homonym, examples)
    return rows


def decide(hits, homonym):
    if hits > 0:
        return "бэклог: измеренный FP"
    if homonym:
        return "бэклог: 0 FP, но легитимный омоним (нужен прозаический корпус)"
    return "ДОБАВИТЬ: 0 FP и нет омонима"


def main():
    paths = sorted(glob.glob("data/synth/synth_*_clean.txt"))
    rows = measure(paths)
    print("Замер словарных кандидатов на %d чистых synth-документах.\n"
          "Критерий добавления: 0 FP И нет легитимного омонима.\n" % len(paths))
    print("%-28s %-4s %-7s %-20s %s"
          % ("кандидат", "FP", "омоним", "примеры", "решение"))
    for name, (hits, homonym, ex) in rows.items():
        print("%-28s %-4d %-7s %-20s %s"
              % (name, hits, "да" if homonym else "нет",
                 ", ".join(ex) or "—", decide(hits, homonym)))


if __name__ == "__main__":
    main()
