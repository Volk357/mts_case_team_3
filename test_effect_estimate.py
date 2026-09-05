#!/usr/bin/env python3
"""Тесты модели прикидки эффекта.

Проверяется три вещи.

1. Согласованность формул. Порог цены возврата, порог доли covered и сам
   эффект считаются по-разному, и если разъедутся, на защите прозвучат два
   несовместимых числа. В точке каждого порога эффект обязан быть нулевым.

2. Отсутствие двойного счёта. Выгода считается ОТ ВОЗВРАТОВ, поэтому она
   не имеет права зависеть от числа замечаний: сколько бы замечаний ни
   указывало на один пробел, предотвращают они один возврат.

3. Зависимость порога от R. Порог обратно пропорционален числу возвратов
   на документ и потому не может называться без этого числа.

Запуск: python3 test_effect_estimate.py
"""
from effect_estimate import (
    FINDINGS_PER_DOC,
    RECALL_ON_DEFECTS,
    RUN_MINUTES,
    SCENARIOS,
    break_even_covered,
    break_even_return_cost,
    costs,
    effect,
    prevented_returns,
)

EPS = 1e-9


def test_measured_constants():
    """Замеренные величины не должны разъехаться с demo-runbook и score.py."""
    assert FINDINGS_PER_DOC == 20, FINDINGS_PER_DOC
    assert abs(RUN_MINUTES * 60 - 70) < EPS, RUN_MINUTES
    assert abs(RECALL_ON_DEFECTS - 0.88) < EPS, RECALL_ON_DEFECTS


def test_find_rate_never_above_measured_recall():
    """Полнота по дефектам — верхняя граница, а не значение по умолчанию.
    Вероятность предотвратить целый возврат не может быть выше неё:
    возврат может вызываться несколькими дефектами сразу, и тогда найти
    надо все существенные. Если сценарий уйдёт выше — тест упадёт."""
    for name, s in SCENARIOS.items():
        assert s["find_rate"] <= RECALL_ON_DEFECTS + EPS, (name, s["find_rate"])
    # и хотя бы один сценарий должен лежать строго ниже границы
    assert any(s["find_rate"] < RECALL_ON_DEFECTS - EPS
               for s in SCENARIOS.values())


def test_find_rate_not_silently_defaulted():
    """find_rate — обязательный параметр во всех формулах. Значения по
    умолчанию быть не должно, иначе замеренная полнота снова незаметно
    подставится как вероятность предотвращения возврата."""
    import inspect
    from effect_estimate import (break_even_covered, break_even_return_cost,
                                 effect, prevented_returns)
    for fn in (prevented_returns, break_even_return_cost, effect,
               break_even_covered):
        sig = inspect.signature(fn)
        param = sig.parameters["find_rate"]
        assert param.default is inspect.Parameter.empty, fn.__name__


def test_benefit_independent_of_findings_count():
    """Главная защита от двойного счёта: выгода считается от возвратов и не
    зависит от того, сколько замечаний выдал инструмент. Если модель снова
    начнёт умножать выгоду на число замечаний, тест упадёт."""
    a = prevented_returns(1.0, 0.5, 0.75)
    b = prevented_returns(1.0, 0.5, 0.75)
    assert abs(a - b) < EPS
    # выгода при 5 и при 500 замечаниях одинакова — меняются только затраты
    e_small = effect(5, 1.5, 1.0, 0.5, 0.75, 120)
    e_big = effect(500, 1.5, 1.0, 0.5, 0.75, 120)
    benefit_small = e_small + costs(5, 1.5)
    benefit_big = e_big + costs(500, 1.5)
    assert abs(benefit_small - benefit_big) < 1e-6, (benefit_small, benefit_big)


def test_prevented_never_exceeds_returns():
    """Предотвратить можно только те возвраты, которые бывают. Ни при каких
    covered и recall результат не должен превысить R."""
    for r in (0.2, 0.5, 1.0, 3.0):
        assert prevented_returns(r, 1.0, 1.0) <= r + EPS
        assert prevented_returns(r, 0.7, 0.75) <= r + EPS


def test_costs_scale_with_all_findings():
    """Затраты растут по ПОЛНОМУ числу замечаний, включая бесполезные, —
    так цена ложных срабатываний попадает в модель."""
    assert abs(costs(20, 1.5) - (20 * 1.5 + RUN_MINUTES)) < EPS
    assert costs(40, 1.5) > costs(20, 1.5)


def test_threshold_inversely_proportional_to_returns():
    """Порог обратно пропорционален R: вдвое реже возвраты — вдвое выше порог.
    Отсюда и запрет называть порог без числа кейсодателя."""
    s = SCENARIOS["база"]
    high = break_even_return_cost(20, s["t_check"], 0.5, s["covered"], s["find_rate"])
    low = break_even_return_cost(20, s["t_check"], 1.0, s["covered"], s["find_rate"])
    assert high is not None and low is not None
    assert abs(high - 2 * low) < 1e-6, (high, low)


def test_r_one_is_not_conservative():
    """R = 1 не является нижней границей: при более редких возвратах порог
    строго выше, а значит вывод при R = 1 оптимистичнее реальности."""
    s = SCENARIOS["база"]
    at_one = break_even_return_cost(20, s["t_check"], 1.0, s["covered"], s["find_rate"])
    at_third = break_even_return_cost(20, s["t_check"], 0.3, s["covered"], s["find_rate"])
    assert at_third > at_one, (at_third, at_one)


def test_break_even_return_cost_is_zero_effect():
    """В точке порога цены возврата эффект строго нулевой — во всех сценариях
    и при любом числе возвратов на документ."""
    for name, s in SCENARIOS.items():
        for r in (0.2, 0.5, 1.0, 2.0):
            c = break_even_return_cost(20, s["t_check"], r, s["covered"], s["find_rate"])
            assert c is not None, (name, r)
            e = effect(20, s["t_check"], r, s["covered"], s["find_rate"], c)
            assert abs(e) < 1e-6, (name, r, c, e)


def test_break_even_covered_is_zero_effect():
    """В точке порога covered эффект тоже нулевой: две формулы порога
    согласованы друг с другом и с формулой эффекта."""
    for name, s in SCENARIOS.items():
        for return_cost in (120, 480, 960):
            cov = break_even_covered(20, s["t_check"], 1.0, s["find_rate"], return_cost)
            if cov is None:
                continue
            e = effect(20, s["t_check"], 1.0, cov, s["find_rate"], return_cost)
            assert abs(e) < 1e-6, (name, return_cost, cov, e)


def test_break_even_covered_none_when_unreachable():
    """Доля не бывает больше единицы. Если даже covered = 1 не окупает затрат,
    честный ответ — None, а не число больше единицы."""
    # затраты 61.17 мин, выгода максимум 0.5 * 1.0 * 0.6 * 60 = 18 мин
    assert break_even_covered(20, 3.0, 0.5, 0.6, 60) is None
    # дорогой возврат — порог существует и лежит СТРОГО внутри единицы
    cov = break_even_covered(20, 3.0, 0.5, 0.6, 600)
    assert cov is not None and 0 < cov < 1, cov


def test_break_even_covered_excludes_unit_boundary():
    """Граничная точка covered = 1 не является окупаемостью: эффект в ней
    ровно нулевой, а окупаемость определена как строго положительный эффект.
    Значит порог, требующий covered > 1, недостижим и обязан давать None —
    единообразно с тем, как окупаемость трактуется в отчёте."""
    # подберём цену возврата, при которой порог попадает ровно в единицу
    n, t_check, r, find_rate = 20, 1.5, 1.0, 0.75
    exact = costs(n, t_check) / (r * find_rate)  # тогда value == 1.0
    assert break_even_covered(n, t_check, r, find_rate, exact) is None
    # в этой точке эффект при covered = 1 действительно нулевой, а не плюсовой
    e = effect(n, t_check, r, 1.0, find_rate, exact)
    assert abs(e) < 1e-6, e
    # чуть дороже — порог появляется и лежит строго внутри единицы
    cov = break_even_covered(n, t_check, r, find_rate, exact * 1.05)
    assert cov is not None and cov < 1, cov


def test_no_prevention_no_payback():
    """Нет возвратов или ни один из них не нашей природы — окупаемости нет
    ни при какой цене возврата."""
    assert break_even_return_cost(20, 1.5, 0.0, 0.5, 0.75) is None
    assert break_even_return_cost(20, 1.5, 1.0, 0.0, 0.75) is None


def test_effect_negative_without_value():
    """Если предотвращать нечего, эффект равен минус затратам: проверка,
    что разбор выдачи действительно вычитается."""
    e = effect(20, 1.5, 1.0, 0.0, 0.75, 120)
    assert abs(e + costs(20, 1.5)) < EPS, e
    assert e < 0


def test_effect_monotonic_in_return_cost():
    """Чем дороже возврат, тем больше эффект."""
    s = SCENARIOS["база"]
    prev = None
    for c in (0, 30, 60, 120, 240):
        e = effect(20, s["t_check"], 1.0, s["covered"], s["find_rate"], c)
        if prev is not None:
            assert e > prev, (c, e, prev)
        prev = e


def test_scenarios_ordered():
    """Пессимизм обязан давать порог выше базы, база — выше оптимизма.
    Если вилка перестанет быть упорядоченной, сценарии названы неверно."""
    th = {name: break_even_return_cost(20, s["t_check"], 1.0, s["covered"], s["find_rate"])
          for name, s in SCENARIOS.items()}
    assert th["пессимизм"] > th["база"] > th["оптимизм"], th


if __name__ == "__main__":
    passed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            passed += 1
            print("ok  %s" % name)
    print("\n%d тестов пройдено" % passed)
