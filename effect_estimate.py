#!/usr/bin/env python3
"""
Прикидка практического эффекта инструмента на одном документе описания витрины.

Зачем отдельный скрипт, а не абзац в презентации: чисел кейсодателя про
возвраты ТЗ у нас нет, и подставить их надо будет вживую. Скрипт считает не
«экономию» (её без этих чисел не посчитать), а ПОРОГ — при какой цене одного
возврата ТЗ инструмент окупается.

Считаем ОТ ВОЗВРАТОВ, а не от замечаний. Счёт от замечаний («столько-то
замечаний предотвращают возврат») даёт двойной счёт: несколько замечаний
одного документа могут указывать на один и тот же пробел и предотвращать
один и тот же возврат. Ограничить сумму сверху — не значит устранить двойной
счёт, поэтому единица выгоды здесь — сам возврат.

Модель на один документ:

    предотвр = R * covered * find_rate  возвратов
    выгода   = предотвр * C             минут
    затраты  = N * t_check + T          разбор выдачи плюс сам прогон, минут
    эффект   = выгода - затраты

    N          замечаний на документ                  20   ЗАМЕРЕНО
    T          время прогона, мин                     1.17 ЗАМЕРЕНО (70 с)
    t_check    минут на разбор одного замечания       ДОПУЩЕНИЕ (вилка)
    covered    доля возвратов, вызванных дефектами
               документации из нашей таксономии       ДОПУЩЕНИЕ (вилка)
    find_rate  доля таких возвратов, чью причину
               инструмент реально находит             ДОПУЩЕНИЕ (вилка)
    R          возвратов ТЗ на документ в среднем     ЧИСЛО КЕЙСОДАТЕЛЯ
    C          цена одного возврата ТЗ, минут работы  ЧИСЛО КЕЙСОДАТЕЛЯ

⚠️ find_rate — это НЕ наша полнота 88%. Полнота замерена по дефектам, а здесь
нужна вероятность предотвратить целый ВОЗВРАТ, и переход между ними не доказан:
возврат может вызываться несколькими дефектами сразу, и тогда найти надо все
существенные, а не один. Поэтому 0.88 взята лишь верхней границей вилки
(оптимистичный сценарий), а база и пессимизм лежат заметно ниже.

Отсюда порог, при котором эффект равен нулю:

    C_крит = (N * t_check + T) / (R * covered * find_rate)

Читается так: «инструмент окупается, если один возврат ТЗ стоит дороже
C_крит минут работы». Ниже порога — не окупается, и это надо говорить.

⚠️ Порог обратно пропорционален R и НЕ называется без него. R = 1 не является
консервативным значением: если возвращают не каждый документ, R меньше единицы
и порог соответственно выше. Поэтому без --returns-per-doc печатается шкала
порога по R, а не одно число.

Цена ложных срабатываний учтена: разбирать приходится все N замечаний, включая
бесполезные, поэтому в затратах стоит полное N, а не только полезная часть.

Чего модель НЕ утверждает:
  * инструмент не заменяет ревьюера — он идёт ПЕРЕД ним, поэтому время
    ручного ревью из затрат не вычитается и в выгоду не записывается;
  * время автора на исправление найденного пробела не считается выгодой:
    оно было бы потрачено всё равно, просто позже и дороже;
  * find_rate ничем не замерен: полнота 88% относится к дефектам, а не к
    возвратам, и вдобавок замерена на синтетическом эталоне — перенос на
    реальные документы заказчика тоже не доказан (риск R2).

Запуск:
    python3 effect_estimate.py                        шкала порога по R
    python3 effect_estimate.py --returns-per-doc 0.5  порог при известном R
    python3 effect_estimate.py --returns-per-doc 0.5 --return-cost 120
    python3 effect_estimate.py --returns-per-doc 0.5 --return-cost 120 \
                               --docs-per-month 40
    python3 effect_estimate.py --sensitivity --returns-per-doc 0.5 \
                               --return-cost 120
"""

import argparse

# --- Замерено, не предполагается -------------------------------------------

# Боевой прогон 4 сентября через туннель до модели: 20 замечаний за 70 секунд
# от загрузки файла до списка на экране (docs/demo-runbook.md).
FINDINGS_PER_DOC = 20
RUN_MINUTES = 70 / 60

# Полнота по месту на эталоне из 5 синтетических документов (57/65), меньшее
# из четырёх наблюдений. ⚠️ В модели НЕ используется как вероятность
# предотвратить возврат: это полнота по дефектам, а не по возвратам. Служит
# только верхней границей вилки find_rate — выше неё уходить заведомо нельзя.
RECALL_ON_DEFECTS = 0.88

# Медиана по 26 реальным карточкам из results/final и results/final2:
# цитата + объяснение + что уточнить = 63 слова. Обоснование вилки t_check.
WORDS_PER_FINDING = 63

# Шкала возвратов на документ для случая, когда числа кейсодателя нет.
RETURNS_SCALE = (0.2, 0.3, 0.5, 1.0, 1.5)


# --- Сценарии допущений -----------------------------------------------------
#
# t_check  63 слова технического текста читаются за 20-25 с; цитата дословная
#          и раздел указан, поэтому навигация по документу дешёвая. База
#          1.5 мин закладывает сверку с документом и решение; 3 мин — если
#          ревьюер перечитывает раздел целиком, 1 мин — если доверяет цитате.
# covered  какая доля возвратов ТЗ вообще вызвана дефектами описания из нашей
#          таксономии, а не бизнес-решениями, сменой требований или причинами
#          вне документа. Опоры в замерах НЕТ — самое слабое место модели.
# find_rate вероятность, что инструмент найдёт причину такого возврата.
#          Верхняя граница 0.88 — наша полнота по дефектам; принимать её за
#          вероятность предотвращения возврата нельзя (возврат может вызываться
#          несколькими дефектами сразу), поэтому база и пессимизм ниже.

SCENARIOS = {
    "пессимизм": {"t_check": 3.0, "covered": 0.30, "find_rate": 0.60},
    "база": {"t_check": 1.5, "covered": 0.50, "find_rate": 0.75},
    "оптимизм": {"t_check": 1.0, "covered": 0.70, "find_rate": RECALL_ON_DEFECTS},
}


def costs(n, t_check, run_minutes=RUN_MINUTES):
    """Затраты на один документ, минут: разбор всей выдачи плюс сам прогон.

    Умножается полное n, а не полезная часть: разбирать приходится и ложные
    замечания — именно так цена низкой точности попадает в модель.
    """
    return n * t_check + run_minutes


def prevented_returns(returns_per_doc, covered, find_rate):
    """Сколько возвратов ТЗ предотвращено на одном документе.

    Единица счёта — возврат, а не замечание: сколько бы замечаний ни указывало
    на один и тот же пробел, предотвращают они один возврат.
    """
    return returns_per_doc * covered * find_rate


def break_even_return_cost(n, t_check, returns_per_doc, covered, find_rate,
                           run_minutes=RUN_MINUTES):
    """Цена возврата ТЗ, начиная с которой инструмент окупается.

    Окупаемостью считается СТРОГО положительный эффект, поэтому возвращённое
    значение — точка нулевого эффекта, а окупается всё, что строго выше неё.

    Возвращает None, если предотвращать нечего (нулевой R, covered или
    find_rate): тогда окупаемость невозможна ни при какой цене возврата.
    """
    prevented = prevented_returns(returns_per_doc, covered, find_rate)
    if prevented <= 0:
        return None
    return costs(n, t_check, run_minutes) / prevented


def effect(n, t_check, returns_per_doc, covered, find_rate, return_cost,
           run_minutes=RUN_MINUTES):
    """Чистый эффект на один документ в минутах при известной цене возврата."""
    prevented = prevented_returns(returns_per_doc, covered, find_rate)
    return prevented * return_cost - costs(n, t_check, run_minutes)


def break_even_covered(n, t_check, returns_per_doc, find_rate, return_cost,
                       run_minutes=RUN_MINUTES):
    """Доля возвратов «нашей природы», выше которой инструмент окупается.

    Возвращает None, если порог физически недостижим. Доля не бывает больше
    единицы, а окупаемость требует СТРОГО положительного эффекта, поэтому
    ровно единица тоже недостижима: при covered = 1 эффект был бы нулевым,
    а не положительным. Отсюда отсечка value >= 1, согласованная с тем, как
    окупаемость определена в break_even_return_cost и в отчёте.
    """
    denom = returns_per_doc * find_rate * return_cost
    if denom <= 0:
        return None
    value = costs(n, t_check, run_minutes) / denom
    if value >= 1:
        return None
    return value


def _fmt(minutes):
    if minutes is None:
        return "—"
    if abs(minutes) >= 60:
        return "%.0f мин (%.1f ч)" % (minutes, minutes / 60)
    return "%.0f мин" % minutes


def _print_measured(n, run_minutes):
    print("Замерено:  %d замечаний за %.0f с; карточка замечания %d слов"
          % (n, run_minutes * 60, WORDS_PER_FINDING))
    print("           документ кейсодателя ~400 слов, выдача ~%d слов"
          % (n * WORDS_PER_FINDING))
    print("Не замерено: доля возвратов нашей природы и вероятность найти их")
    print("           причину. Полнота %.0f%% относится к дефектам, а не к"
          % (RECALL_ON_DEFECTS * 100))
    print("           возвратам, и служит лишь верхней границей вилки.")


def scale(n, run_minutes=RUN_MINUTES):
    """Порог окупаемости как функция числа возвратов на документ.

    Печатается, когда числа кейсодателя нет: одно число порога без R назвать
    нельзя, потому что порог обратно пропорционален R.
    """
    print("Порог окупаемости в зависимости от числа возвратов ТЗ на документ")
    print("=" * 70)
    _print_measured(n, run_minutes)
    print()
    print("Ниже — цена одного возврата, начиная с которой инструмент окупается.")
    print()

    header = "%-14s" % "возвратов"
    for name in SCENARIOS:
        header += "%19s" % name
    print(header)
    print("%-14s" % "на документ")
    print("-" * 71)
    for r in RETURNS_SCALE:
        row = "%-14.1f" % r
        for s in SCENARIOS.values():
            be = break_even_return_cost(n, s["t_check"], r, s["covered"],
                                        s["find_rate"], run_minutes)
            row += "%19s" % (_fmt(be) if be is not None else "не окупается")
        print(row)
    print()
    print("Допущения сценариев:")
    for name, s in SCENARIOS.items():
        print("  %-11s разбор %.1f мин/шт, covered %.2f, find_rate %.2f"
              % (name, s["t_check"], s["covered"], s["find_rate"]))
    print()
    print("⚠️ R = 1 НЕ является консервативным значением. Если возвращают не")
    print("   каждый документ, R меньше единицы, а порог соответственно выше.")
    print("   Поэтому порог без числа кейсодателя одним числом не называется.")
    print()
    print("Нужны от кейсодателя:")
    print("  1. сколько описаний витрин проходит ревью в месяц  --docs-per-month")
    print("  2. сколько возвратов приходится на документ        --returns-per-doc")
    print("  3. сколько времени стоит один возврат              --return-cost")


def report(n, returns_per_doc, return_cost=None, docs_per_month=None,
           run_minutes=RUN_MINUTES):
    print("Прикидка эффекта на один документ описания витрины")
    print("=" * 70)
    _print_measured(n, run_minutes)
    print("Задано:    %.2f возврата ТЗ на документ" % returns_per_doc)
    print()

    print("%-11s %8s %8s %8s %10s %9s %14s" %
          ("сценарий", "разбор", "covered", "find", "предотвр", "затраты",
           "порог цены"))
    print("%-11s %8s %8s %8s %10s %9s %14s" %
          ("", "мин/шт", "", "rate", "возвратов", "мин", "возврата ТЗ"))
    print("-" * 74)
    thresholds = {}
    for name, s in SCENARIOS.items():
        c = costs(n, s["t_check"], run_minutes)
        prevented = prevented_returns(returns_per_doc, s["covered"],
                                      s["find_rate"])
        be = break_even_return_cost(n, s["t_check"], returns_per_doc,
                                    s["covered"], s["find_rate"], run_minutes)
        thresholds[name] = be
        print("%-11s %8.1f %8.2f %8.2f %10.3f %9.0f %14s"
              % (name, s["t_check"], s["covered"], s["find_rate"], prevented, c,
                 _fmt(be) if be is not None else "не окупается"))
    print()

    if thresholds["база"] is None:
        print("При %.2f возврата на документ предотвращать нечего:"
              % returns_per_doc)
        print("инструмент не окупается ни при какой цене возврата.")
    else:
        print("При %.2f возврата на документ инструмент окупается, если один"
              % returns_per_doc)
        print("возврат ТЗ стоит дороже %s (база); вилка допущений: %s — %s."
              % (_fmt(thresholds["база"]), _fmt(thresholds["оптимизм"]),
                 _fmt(thresholds["пессимизм"])))
    print()

    if return_cost is None:
        print("Чтобы посчитать саму экономию, добавьте --return-cost <мин>:")
        print("сколько рабочего времени стоит один возврат ТЗ.")
        return

    print("Подставлена цена возврата ТЗ: %s" % _fmt(return_cost))
    print("-" * 74)
    for name, s in SCENARIOS.items():
        e = effect(n, s["t_check"], returns_per_doc, s["covered"],
                   s["find_rate"], return_cost, run_minutes)
        mark = "окупается" if e > 0 else "НЕ окупается"
        print("  %-11s эффект %+8.0f мин на документ   %s" % (name, e, mark))
    print()

    if docs_per_month:
        print("При %d документах в месяц:" % docs_per_month)
        for name, s in SCENARIOS.items():
            e = effect(n, s["t_check"], returns_per_doc, s["covered"],
                       s["find_rate"], return_cost, run_minutes)
            m = e * docs_per_month
            print("  %-11s %+.0f мин/мес (%+.1f ч/мес)" % (name, m, m / 60))
        print()

    print("Порог по доле возвратов «нашей природы» при этой цене возврата:")
    for name, s in SCENARIOS.items():
        bc = break_even_covered(n, s["t_check"], returns_per_doc,
                                s["find_rate"], return_cost, run_minutes)
        if bc is None:
            print("  %-11s не окупается ни при какой достижимой доле" % name)
        else:
            print("  %-11s covered > %.2f" % (name, bc))


def sensitivity(n, returns_per_doc, return_cost, run_minutes=RUN_MINUTES):
    """Как меняется эффект базового сценария при разной доле covered."""
    s = SCENARIOS["база"]
    print("Чувствительность базового сценария к доле возвратов «нашей природы»")
    print("(цена возврата %s, %.2f возврата на документ, разбор %.1f мин/шт,"
          % (_fmt(return_cost), returns_per_doc, s["t_check"]))
    print(" find_rate %.2f)" % s["find_rate"])
    print("-" * 74)
    for i in range(0, 11):
        covered = i / 10
        e = effect(n, s["t_check"], returns_per_doc, covered, s["find_rate"],
                   return_cost, run_minutes)
        print("  covered=%.1f   эффект %+8.0f мин на документ" % (covered, e))


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--findings", type=int, default=FINDINGS_PER_DOC,
                    help="замечаний на документ (замерено: %d)" % FINDINGS_PER_DOC)
    ap.add_argument("--run-seconds", type=float, default=RUN_MINUTES * 60,
                    help="время прогона в секундах (замерено: 70)")
    ap.add_argument("--returns-per-doc", type=float,
                    help="возвратов ТЗ на документ в среднем (число кейсодателя); "
                         "без него печатается шкала порога по этому параметру")
    ap.add_argument("--return-cost", type=float,
                    help="цена одного возврата ТЗ в минутах работы (число кейсодателя)")
    ap.add_argument("--docs-per-month", type=int,
                    help="документов в месяц (число кейсодателя)")
    ap.add_argument("--sensitivity", action="store_true",
                    help="таблица чувствительности к доле возвратов «нашей природы»")
    args = ap.parse_args()

    if args.findings <= 0:
        ap.error("--findings должно быть больше нуля")
    if args.returns_per_doc is not None and args.returns_per_doc < 0:
        ap.error("--returns-per-doc не может быть отрицательным")

    run_minutes = args.run_seconds / 60

    if args.sensitivity:
        if args.return_cost is None or args.returns_per_doc is None:
            ap.error("--sensitivity требует --return-cost и --returns-per-doc")
        sensitivity(args.findings, args.returns_per_doc, args.return_cost,
                    run_minutes)
        return

    if args.returns_per_doc is None:
        if args.return_cost is not None or args.docs_per_month is not None:
            ap.error("расчёт эффекта требует --returns-per-doc: "
                     "без числа возвратов на документ выгода не считается")
        scale(args.findings, run_minutes)
        return

    report(args.findings, args.returns_per_doc, args.return_cost,
           args.docs_per_month, run_minutes)


if __name__ == "__main__":
    main()
