#!/usr/bin/env python3
"""Тесты диагностики stolen_by_neighbor в score.match.

Блокер ревью №1: метка «отдано соседу» должна ставиться ТОЛЬКО когда сильное
(place>=threshold) замечание реально занято другим дефектом, а не когда оно
свободно, но проиграло жадный ранг из-за бонуса за верный тип.

Запуск: python test_score.py
"""
from score import match


def _truth(defects):
    return {"doc": "t", "defects": defects}


def test_genuine_steal():
    """Два presence-дефекта на одну цитату. Одно замечание, точно совпадающее
    с обоими, достаётся первому; второй не засчитан и помечен stolen."""
    truth = _truth([
        {"defect_id": "A", "defect_class": "presence", "detectable_by": "llm",
         "quote": "поле X без описания", "anchor_node": "s.a"},
        {"defect_id": "B", "defect_class": "presence", "detectable_by": "llm",
         "quote": "поле X без описания", "anchor_node": "s.b"},
    ])
    findings = [{"defect_id": "A", "quote": "поле X без описания"}]
    rows, _ = match(truth, findings)
    by = {r["defect_id"]: r for r in rows}
    assert by["A"]["found_by_place"] is True, by["A"]
    assert by["B"]["found_by_place"] is False, by["B"]
    assert by["B"]["stolen_by_neighbor"] is True, "B должен быть 'отдан соседу'"
    assert by["A"]["stolen_by_neighbor"] is False


def test_unused_above_threshold_not_stolen():
    """Замечание с верным типом, но низкой локализацией (0.5<0.6) выигрывает ранг
    из-за бонуса +1 и делает hit=False. Второе замечание чужого типа точно
    совпадает (place=1.0), но остаётся СВОБОДНЫМ. Это НЕ кража."""
    truth = _truth([
        {"defect_id": "TARGET", "defect_class": "presence", "detectable_by": "llm",
         "quote": "альфа бета", "anchor_node": "s.t"},
    ])
    findings = [
        # верный тип, перекрытие 1/2 токенов при вложенности нет → place=0.5
        {"defect_id": "TARGET", "quote": "альфа гамма"},
        # чужой тип, дословное вложение → place=1.0, но не выбран (ранг 1.0<1.5)
        {"defect_id": "OTHER", "quote": "альфа бета"},
    ]
    rows, _ = match(truth, findings)
    r = rows[0]
    assert r["found_by_place"] is False, r
    assert r["stolen_by_neighbor"] is False, \
        "свободный finding выше порога не должен считаться украденным"


def test_regression_recall_unchanged():
    """Строгий found_by_place не зависит от диагностики: одиночное точное
    совпадение засчитывается, stolen=False."""
    truth = _truth([
        {"defect_id": "A", "defect_class": "presence", "detectable_by": "llm",
         "quote": "точная цитата дефекта", "anchor_node": "s.a"},
    ])
    findings = [{"defect_id": "A", "quote": "точная цитата дефекта"}]
    rows, _ = match(truth, findings)
    assert rows[0]["found_by_place"] is True
    assert rows[0]["found_by_type"] is True
    assert rows[0]["stolen_by_neighbor"] is False


def test_gather_drops_deterministic_llm_findings():
    """Детерминированные типы из модельных находок отбрасываются: их источник —
    формальный слой. Иначе модельные FP таких типов засоряют счёт."""
    import json
    import os
    import tempfile
    from score import gather, deterministic_types
    assert "NO_FILTER_DESCRIPTION" in deterministic_types()
    d = tempfile.mkdtemp()
    json.dump({"findings": [
        {"defect_id": "NO_FILTER_DESCRIPTION", "quote": "модельный ложный"},
        {"defect_id": "AMBIGUOUS_LOGIC", "quote": "настоящий llm"}]},
        open(os.path.join(d, "doc_full2.json"), "w", encoding="utf-8"))
    out, _ = gather(d, "doc", "_full2")
    ids = [f["defect_id"] for f in out]
    assert "NO_FILTER_DESCRIPTION" not in ids, "детерм. тип из LLM должен отброситься"
    assert "AMBIGUOUS_LOGIC" in ids, "llm-тип остаётся"


def test_findings_cli_filters_deterministic():
    """Режим score.py --truth --findings (README) тоже отбрасывает детерм. типы
    из модельного файла. Проверяем через реальный запуск CLI."""
    import json
    import os
    import subprocess
    import sys
    import tempfile
    d = tempfile.mkdtemp()
    tp = os.path.join(d, "t_truth.json")
    fp = os.path.join(d, "t_full2.json")
    # эталонный дефект не совпадает ни с одной находкой → обе идут в «вне эталона»,
    # где llm-тип должен быть, а детерм. — отфильтрован
    json.dump({"doc": "t", "defects": [
        {"defect_id": "NO_DEDUP_OR_KEY", "defect_class": "presence",
         "detectable_by": "llm", "quote": "несовпадающая эталонная цитата",
         "anchor_node": "s.a"}]},
        open(tp, "w", encoding="utf-8"), ensure_ascii=False)
    json.dump({"findings": [
        {"defect_id": "NO_FILTER_DESCRIPTION", "quote": "модельный ложный детерм"},
        {"defect_id": "AMBIGUOUS_LOGIC", "quote": "настоящая llm находка"}]},
        open(fp, "w", encoding="utf-8"), ensure_ascii=False)
    here = os.path.dirname(os.path.abspath(__file__))
    out = subprocess.run(
        [sys.executable, os.path.join(here, "score.py"), "--truth", tp,
         "--findings", fp],
        cwd=here, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr        # иначе пустой stdout ложно пройдёт
    assert "AMBIGUOUS_LOGIC" in out.stdout, "llm-тип должен присутствовать в выводе"
    assert "NO_FILTER_DESCRIPTION" not in out.stdout, \
        "детерм. тип из модельного файла должен отброситься в --findings режиме"


if __name__ == "__main__":
    test_genuine_steal()
    test_unused_above_threshold_not_stolen()
    test_regression_recall_unchanged()
    test_gather_drops_deterministic_llm_findings()
    test_findings_cli_filters_deterministic()
    print("все тесты пройдены")
