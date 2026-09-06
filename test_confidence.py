#!/usr/bin/env python3
"""
Тесты калибровки уверенности (пункт 8 аудита).

Аудит: «0.95–0.99 выглядит как вероятность, но вычисляется эвристически
из severity. Такой показатель вводит пользователя в заблуждение».

Претензия подтвердилась замером и оказалась хуже, чем звучала: показатель
был не просто неоткалиброван, а местами ИНВЕРТИРОВАН — заявленные 0.95
у слоя модели давали 20% попаданий, а 0.85 — 70%. Причиной была надбавка
за согласие проходов (`merged_count`): она набирала высокие значения там,
где достоверность не росла.

Замер (5 synth-документов, 107 замечаний, сопоставление той же функцией,
что считает полноту): взвешенная средняя ошибка калибровки была 0.344,
после правки 0.036.

Здесь проверяется механика: значения соответствуют замеру, надбавки нет,
и — главное — изменение уверенности НЕ трогает порядок и отбор замечаний,
то есть полнота остаётся прежней.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import docreview                                               # noqa: E402
import run_review                                              # noqa: E402


def _f(severity="medium", merged=1, quote="цитата замечания в документе",
       did="X"):
    f = {"quote": quote, "defect_id": did, "severity": severity,
         "explanation": "e", "suggestion": "s"}
    if merged > 1:
        f["merged_count"] = merged
    return f


# --- 1. Значения соответствуют замеру ------------------------------------

def test_model_confidence_matches_measured_hit_rate():
    """Заявленное — это замеренная доля попаданий, а не вес важности.

    high 0.5 при замеренных 51% (21/41), medium 0.2 при 19% (6/32).
    """
    assert docreview._confidence(_f("high"), False) == 0.5
    assert docreview._confidence(_f("medium"), False) == 0.2


def test_rare_severities_are_conservative_not_optimistic():
    """low и clarification: наблюдений 5 и 3 — калибровать по ним нельзя.

    Замер дал low 60%, но пять наблюдений не основание объявить 0.6.
    Берётся оценка medium: занизить безопаснее, чем завысить показатель,
    который пользователь читает как «насколько можно верить».
    """
    for sev in ("low", "clarification"):
        assert docreview._confidence(_f(sev), False) == 0.2, sev
    # critical в эталоне не встречался вовсе — приравнен к high, не выше.
    assert docreview._confidence(_f("critical"), False) == 0.5


def test_rule_layer_is_high_but_not_certain():
    """Слой правил 0.95 при замеренных 26/26.

    Единица означала бы «ошибок не бывает», а известный промах есть:
    SCHEMA_TYPE_MISMATCH на synth_2, где соседняя мутация стёрла вторую
    сторону сравнения.
    """
    assert docreview._confidence(_f("medium"), True) == 0.95
    assert docreview._confidence(_f("high"), True) == 0.95
    # Важность на слой правил не влияет: он точен по построению, а не
    # потому, что нашёл что-то важное.
    assert docreview._confidence(_f("low"), True) == 0.95


def test_unknown_severity_falls_back_to_the_lowest():
    """Неизвестная важность не должна давать высокую уверенность."""
    assert docreview._confidence(_f("невиданное"), False) == 0.2


def test_merged_count_no_longer_inflates_confidence():
    """Надбавка за согласие проходов убрана — она разрушала шкалу.

    Именно она делала 0.95 и 0.99, которые калибровались хуже базовых:
    0.95 → 20% попаданий против 0.90 → 69%.
    """
    base = docreview._confidence(_f("high", merged=1), False)
    for merged in (2, 3, 5, 12):
        assert docreview._confidence(_f("high", merged=merged), False) == base, merged


def test_confidence_stays_inside_the_contract_range():
    """Контракт требует 0 ≤ confidence ≤ 1."""
    for det in (True, False):
        for sev in ("critical", "high", "medium", "low", "clarification", "?"):
            c = docreview._confidence(_f(sev), det)
            assert 0.0 <= c <= 1.0, (sev, det, c)


# --- 2. Главное: калибровка не двигает полноту ---------------------------

def test_ranking_does_not_depend_on_confidence():
    """Порядок и отбор замечаний не зависят от `_confidence`.

    Это причина, по которой правку можно было делать за сутки до защиты:
    полнота 89% по месту / 78% по типу не меняется. Ранжирование идёт
    через `run_review._priority` (важность × согласие проходов), а
    `_confidence` — только поле выдачи.

    Проверяется подменой: калибровка переворачивается с ног на голову,
    состав и порядок обязаны остаться теми же.
    """
    # Замечаний БОЛЬШЕ потолка (20), иначе отбор не происходит вовсе
    # и тест проверял бы только порядок. Первая версия давала четыре
    # замечания и была отклонена на ревью справедливо.
    #
    # Состав подобран так, чтобы кандидаты стояли на границе отсечения:
    # high не режется никогда, значит режутся medium и low, и именно
    # среди них выбор мог бы зависеть от уверенности, будь она в правиле.
    quotes = ["Замечание номер %02d о содержании раздела документа" % i
              for i in range(26)]
    severities = ["high"] * 6 + ["medium"] * 12 + ["low"] * 8
    merged = [1, 2, 3, 1, 2, 1] + [3, 1, 2, 1, 3, 2, 1, 2, 3, 1, 2, 1] + \
             [2, 1, 3, 1, 2, 1, 3, 1]
    findings = [_f(sev, merged=m, quote=q, did="T%02d" % i)
                for i, (q, sev, m) in enumerate(zip(quotes, severities, merged))]
    doc = "\n".join(quotes)

    def order(result):
        return [(f["defect_id"], f["severity"]) for f in result["findings"]]

    before = docreview.build_review_result(
        doc, "d.txt", "T", [], findings, "r-1", ("mts-net", "0.2"), "m",
        {"fragment": "dict2"}, 1.0)

    # Подмена обязана РАЗЛИЧАТЬ medium и low, иначе тест ничего не проверяет:
    # в боевой калибровке они равны (0.2), сортировка по такому значению
    # порядка не меняет, и подсадка «отбор зависит от уверенности» прошла бы
    # незамеченной. Найдено проверкой на подсадку, первая версия была слепой.
    # Здесь low получает БОЛЬШЕ medium — если бы отбор смотрел на уверенность,
    # срезало бы другие замечания.
    original = dict(docreview._SEV_BASE)
    docreview._SEV_BASE.update({"high": 0.01, "medium": 0.10, "low": 0.99,
                                "clarification": 0.99, "critical": 0.01})
    try:
        after = docreview.build_review_result(
            doc, "d.txt", "T", [], findings, "r-1", ("mts-net", "0.2"), "m",
            {"fragment": "dict2"}, 1.0)
    finally:
        docreview._SEV_BASE.clear()
        docreview._SEV_BASE.update(original)

    # Отбор ДЕЙСТВИТЕЛЬНО состоялся: иначе тест проверял бы только порядок.
    assert len(before["findings"]) == 20, len(before["findings"])
    assert len(findings) > 20, "нужно переполнение потолка"

    # Состав — тот же набор замечаний, а не только их порядок.
    assert {d for d, _ in order(before)} == {d for d, _ in order(after)}
    # И порядок тоже.
    assert order(before) == order(after), (order(before), order(after))
    # А само число, конечно, изменилось — иначе тест ничего не проверял бы.
    assert [f["confidence"] for f in before["findings"]] != \
        [f["confidence"] for f in after["findings"]]


def test_budget_ranking_ignores_confidence_entirely():
    """`run_review._priority` не читает поле `confidence` из находки."""
    a = _f("medium", merged=3, quote="первое замечание документа", did="A")
    b = _f("medium", merged=1, quote="второе замечание документа", did="B")
    a["confidence"], b["confidence"] = 0.01, 0.99
    assert run_review._priority(a) > run_review._priority(b), \
        "порядок должен определяться согласием проходов, а не полем confidence"


# --- 3. Значение доходит до выдачи неизменным ---------------------------

def test_confidence_reaches_the_result():
    result = docreview.build_review_result(
        "Срок хранения данных не определён в документе.",
        "d.txt", "T",
        [_f("medium", quote="Срок хранения данных не определён в документе.",
            did="RULE")],
        [], "r-1", ("mts-net", "0.2"), "m", {"fragment": "dict2"}, 1.0)
    assert result["findings"][0]["confidence"] == 0.95


def test_result_passes_the_contract():
    from contracts.validate_contract import validate_review_result
    findings = [_f("high", quote="Срок хранения данных не определён."),
                _f("medium", quote="Загрузка выполняется ежедневно.", did="Y")]
    result = docreview.build_review_result(
        "Срок хранения данных не определён.\nЗагрузка выполняется ежедневно.",
        "d.txt", "T", [], findings, "run-1", ("mts-net", "0.2"),
        "qwen3:30b-a3b", {"fragment": "dict2", "global": "global"}, 12.0,
        document_sha256="a" * 64)
    validate_review_result(result)


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    for t in TESTS:
        t()
        print("ok  %s" % t.__name__)
    print("\n%d passed" % len(TESTS))
