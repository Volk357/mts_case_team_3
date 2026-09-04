#!/usr/bin/env python3
"""Тесты ранжирования и отсечения по бюджету (пункт 3).

Запуск: python test_run_review.py
"""
import run_review
from run_review import apply_budget, BUDGET_CEILING


def _f(sev, mc=1, quote="цитата дефекта достаточно содержательная"):
    return {"severity": sev, "merged_count": mc, "quote": quote}


def test_under_budget_returns_input_unchanged():
    findings = [_f("high"), _f("medium"), _f("low")]
    keep, dropped = apply_budget(findings, ceiling=20)
    assert dropped == []
    assert keep is findings, "под бюджетом функция возвращает вход без правок"


def test_high_never_cut_even_over_ceiling():
    findings = [_f("high") for _ in range(25)]
    keep, dropped = apply_budget(findings, ceiling=20)
    assert len(keep) == 25 and dropped == []


def test_cap_to_ceiling_high_priority():
    findings = [_f("high") for _ in range(5)] + [_f("medium") for _ in range(30)]
    keep, dropped = apply_budget(findings, ceiling=20)
    assert len(keep) == 20
    assert sum(1 for f in keep if f["severity"] == "high") == 5
    assert len(dropped) == 15 and all(f["severity"] == "medium" for f in dropped)


def test_confident_low_beats_weak_medium():
    # severity × confidence: low с согласием 5 проходов обгоняет medium с 1.
    findings = ([_f("high") for _ in range(19)]
                + [_f("medium", mc=1), _f("low", mc=5)])
    keep, dropped = apply_budget(findings, ceiling=20)
    assert len(keep) == 20
    kept_rest = [f for f in keep if f["severity"] != "high"]
    assert len(kept_rest) == 1 and kept_rest[0]["severity"] == "low", \
        "уверенный low (5) должен обойти едва замеченный medium (1)"
    assert dropped[0]["severity"] == "medium"


def test_content_score_tiebreak():
    # равный severity×confidence (оба medium, mc=1) → решает содержательность.
    findings = ([_f("high") for _ in range(19)]
                + [_f("medium", mc=1, quote="кратко"),
                   _f("medium", mc=1, quote="развёрнутая содержательная цитата дефекта")])
    keep, dropped = apply_budget(findings, ceiling=20)
    kept_rest = [f for f in keep if f["severity"] != "high"]
    assert len(kept_rest) == 1
    assert "развёрнутая" in kept_rest[0]["quote"], "при равном приоритете — цитата содержательнее"


def test_run_full_applies_budget_and_reports_capped(monkeypatch=None):
    # Подменяем проходы модели: 25 medium с разными defect_id (не склеятся).
    fake = [{"quote": f"цитата дефекта номер {i} в документе", "defect_id": f"T{i}",
             "explanation": "e", "suggestion": "s", "severity": "medium"}
            for i in range(25)]
    run_review.run = lambda *a, **k: {
        "findings": fake, "fragments": 1, "total_seconds": 0.0,
        "found_raw": 25, "rejected_count": 0, "reject_reasons": {}, "rejected": []}
    run_review.run_global = lambda *a, **k: {
        "findings": [], "total_seconds": 0.0, "found_raw": 0,
        "rejected_count": 0, "reject_reasons": {}, "rejected": []}
    doc = " ".join(f["quote"] for f in fake)
    res = run_review.run_full(doc, [], "", set(), "", label="full2")
    assert res["verified"] == 20, "потолок применён"
    assert res["capped_away"] == 5 and len(res["capped"]) == 5
    assert len(res["findings"]) == 20


def test_retained_order_follows_priority():
    # Оба остаются в выводе: уверенный low(mc=5) должен идти РАНЬШЕ medium(mc=1),
    # финальная пересортировка по severity этого не отменяет.
    findings = [_f("medium", mc=1), _f("low", mc=5), _f("low", mc=1)]
    keep, dropped = apply_budget(findings, ceiling=2)
    assert len(keep) == 2
    assert keep[0]["severity"] == "low" and keep[0]["merged_count"] == 5
    assert keep[1]["severity"] == "medium"
    assert dropped[0]["severity"] == "low" and dropped[0]["merged_count"] == 1


def test_high_stay_first_in_output():
    findings = [_f("medium", mc=9), _f("high", mc=1), _f("low", mc=1)]
    keep, _ = apply_budget(findings, ceiling=2)
    assert keep[0]["severity"] == "high", "high выводятся первыми, несмотря на mc medium"


def test_run_full_drops_deterministic_type_findings():
    # находки детерминированных типов из модели отбрасываются в run_full;
    # llm-типы остаются. Источник детерм. типов — формальный слой.
    fake = [
        {"quote": "детерм ложный", "defect_id": "NO_FILTER_DESCRIPTION",
         "explanation": "e", "suggestion": "s", "severity": "high"},
        {"quote": "настоящий llm", "defect_id": "AMBIGUOUS_LOGIC",
         "explanation": "e", "suggestion": "s", "severity": "high"}]
    run_review.run = lambda *a, **k: {
        "findings": fake, "fragments": 1, "total_seconds": 0.0,
        "found_raw": 2, "rejected_count": 0, "reject_reasons": {}, "rejected": []}
    run_review.run_global = lambda *a, **k: {
        "findings": [], "total_seconds": 0.0, "found_raw": 0,
        "rejected_count": 0, "reject_reasons": {}, "rejected": []}
    defects = [{"id": "NO_FILTER_DESCRIPTION", "detectable_by": "deterministic"},
               {"id": "AMBIGUOUS_LOGIC", "detectable_by": "llm"}]
    res = run_review.run_full("детерм ложный настоящий llm", defects, "", set(), "",
                              label="full2")
    ids = [f["defect_id"] for f in res["findings"]]
    assert "NO_FILTER_DESCRIPTION" not in ids, "детерм. тип из модели должен отброситься"
    assert "AMBIGUOUS_LOGIC" in ids, "llm-тип остаётся"


def test_default_ceiling_is_20():
    assert BUDGET_CEILING == 20


def test_every_severity_has_rank_and_weight():
    """Значение из SEVERITIES обязано быть в обеих таблицах ранжирования:
    иначе оно молча получит вес medium (блокер ревью 4 сентября — critical
    разрешён схемой, но резался бы раньше high)."""
    for sev in run_review.SEVERITIES:
        assert sev in run_review._SEV_WEIGHT, sev
    assert run_review._sev_rank({"severity": "critical"}) == 0
    assert run_review._sev_rank({"severity": "high"}) == 0
    assert run_review._SEV_WEIGHT["critical"] > run_review._SEV_WEIGHT["high"]


def test_critical_ordered_above_high_in_output():
    # блокер круга 2: проверять надо фактический порядок, а не константы
    items = ([{"severity": "high", "quote": "высокое замечание", "defect_id": "X"},
              {"severity": "critical", "quote": "критичное замечание", "defect_id": "X"}]
             + [{"severity": "medium", "quote": "среднее %d" % i, "defect_id": "Y"}
                for i in range(19)])
    kept, _ = apply_budget(items, BUDGET_CEILING)
    assert kept[0]["severity"] == "critical", [f["severity"] for f in kept[:3]]
    assert kept[1]["severity"] == "high"


def test_critical_not_cut_by_budget():
    crit = [{"severity": "critical", "quote": "критичное замечание %d" % i,
             "defect_id": "X"} for i in range(5)]
    rest = [{"severity": "medium", "quote": "среднее замечание %d" % i,
             "defect_id": "Y", "merged_count": 3} for i in range(30)]
    kept, dropped = apply_budget(crit + rest, BUDGET_CEILING)
    assert all(f in kept for f in crit), "critical не должен резаться бюджетом"


def test_normalize_severity_dictionary_values_pass_through():
    for v in ("high", "medium", "low", "clarification", " HIGH ", "Low."):
        sev, fixed = run_review.normalize_severity(v)
        assert sev == v.strip().lower().strip(".") and fixed is False


def test_normalize_severity_mixed_alphabet_from_real_run():
    # реальный ответ модели на документе кейсодателя: латиница + кириллица
    assert run_review.normalize_severity("clarifiсатио") == ("clarification", True)


def test_normalize_severity_russian_and_garbage():
    assert run_review.normalize_severity("высокая") == ("high", True)
    assert run_review.normalize_severity("низкая") == ("low", True)
    assert run_review.normalize_severity("нечто") == ("medium", True)
    assert run_review.normalize_severity(None) == ("medium", True)


def test_normalize_severity_ambiguous_prefix_falls_back():
    # «cl» подходит и clarification, и (гипотетически) другим — префикс короче 3 не берём
    assert run_review.normalize_severity("cl") == ("medium", True)


def test_verify_normalizes_severity_and_keeps_finding():
    src = "Часовой пояс: UTC\nЕжемесячно (1 раз в месяц)\n"
    findings = [{"quote": "Ежемесячно (1 раз в месяц)", "defect_id": "NO_SCHEDULE",
                 "explanation": "Нет времени запуска.", "suggestion": "Указать окно.",
                 "severity": "clarifiсатио"}]
    kept, dropped = run_review.verify(findings, src, None)
    assert len(kept) == 1 and not dropped
    assert kept[0]["severity"] == "clarification"
    assert kept[0]["severity_raw"] == "clarifiсатио"


def test_prompt_taxonomy_matches_defects_yaml():
    """defects_prompt.yaml — та же таксономия для промпта: состав llm-типов
    и их описания обязаны совпадать с defects.yaml. Расщепление типа, забытое
    в одном файле, — это молча разъехавшийся промпт (блокер ревью 4 сентября)."""
    import re as _re
    import yaml as _yaml
    full = {d["id"]: d for d in _yaml.safe_load(
        open("defects.yaml", encoding="utf-8"))["defects"]}
    prompt = {d["id"]: d for d in _yaml.safe_load(
        open("defects_prompt.yaml", encoding="utf-8"))["defects"]}
    llm = {i for i, d in full.items() if d.get("detectable_by") == "llm"}
    assert set(prompt) == llm, (
        "промпт-таксономия разошлась: лишние %s, недостающие %s"
        % (sorted(set(prompt) - llm), sorted(llm - set(prompt))))
    norm = lambda s: _re.sub(r"\s+", " ", (s or "").strip())
    drift = [i for i in prompt
             if norm(full[i].get("description")) != norm(prompt[i].get("description"))]
    assert not drift, "описания разошлись: %s" % drift


if __name__ == "__main__":
    test_under_budget_returns_input_unchanged()
    test_high_never_cut_even_over_ceiling()
    test_cap_to_ceiling_high_priority()
    test_confident_low_beats_weak_medium()
    test_content_score_tiebreak()
    test_retained_order_follows_priority()
    test_high_stay_first_in_output()
    test_run_full_applies_budget_and_reports_capped()
    test_run_full_drops_deterministic_type_findings()
    test_default_ceiling_is_20()
    test_every_severity_has_rank_and_weight()
    test_critical_ordered_above_high_in_output()
    test_critical_not_cut_by_budget()
    test_normalize_severity_dictionary_values_pass_through()
    test_normalize_severity_mixed_alphabet_from_real_run()
    test_normalize_severity_russian_and_garbage()
    test_normalize_severity_ambiguous_prefix_falls_back()
    test_verify_normalizes_severity_and_keeps_finding()
    test_prompt_taxonomy_matches_defects_yaml()
    print("все тесты пройдены")
