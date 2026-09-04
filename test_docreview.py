#!/usr/bin/env python3
"""Тесты docreview: вывод валиден по контракту Никиты (JSON-схема v1.0).

Запуск: python test_docreview.py
Схема берётся из contracts/review-result.schema.json ветки Никиты (сохранена
локально в /tmp при разработке; тест ищет её по нескольким путям).
"""
import json
import os

try:
    import jsonschema
except ImportError:                       # на свежем клоне без зависимости
    jsonschema = None

from docreview import build_review_result, failed_result


def _validate(obj):
    if jsonschema is not None:
        jsonschema.validate(obj, _schema())

_SCHEMA_PATHS = [
    "/tmp/review-result.schema.json",
    "contracts/review-result.schema.json",
]


def _schema():
    for p in _SCHEMA_PATHS:
        if os.path.exists(p):
            return json.load(open(p, encoding="utf-8"))
    raise SystemExit("схема контракта не найдена: " + ", ".join(_SCHEMA_PATHS))


DOC = ("Структура данных\n"
       "Приемники. Таблица: SCHEMA_X.TABLE_Y\n"
       "Атрибут | Тип | Описание | Обязательность | Источник\n"
       "FIELD_A | string | описание | — | Источник\n"
       "Алгоритм обработки потока\n"
       "Шаг 1. Фильтрация данных\n"
       "Учитываются записи по UTC.\n")

FORMAL = [{"defect_id": "NULLABILITY_UNSPECIFIED",
           "quote": "FIELD_A | string | описание | — | Источник",
           "explanation": "Нет признака обязательности.",
           "suggestion": "Добавить NOT NULL/NULLABLE.", "severity": "medium"}]
LLM = [{"defect_id": "TIMEZONE_UNDEFINED", "quote": "Учитываются записи по UTC.",
        "explanation": "Часовой пояс границ не определён.",
        "suggestion": "Уточнить пояс.", "severity": "high", "merged_count": 2},
       {"defect_id": "NO_SCHEDULE", "quote": "Учитываются записи по UTC.",
        "explanation": "Регламент не указан.", "suggestion": "Указать регламент.",
        "severity": "clarification"}]


def _build():
    return build_review_result(
        DOC, "synth_demo.txt", "txt", FORMAL, LLM, "run-123", "mts-net-v0.2",
        "qwen3:30b-a3b", {"fragment": "dict2", "global": "global"}, 1234,
        warnings=[], total_candidates=5, verified_candidates=3)


def test_completed_result_valid_against_contract():
    _validate(_build())


def test_failed_result_valid_against_contract():
    fr = failed_result("run-9", "CORE_PROCESS_FAILED", "analyze", "boom", True)
    _validate(fr)


def test_severity_and_detected_by_mapping():
    r = _build()
    by_id = {f["defect_id"]: f for f in r["findings"]}
    # clarification-severity → low
    assert by_id["NO_SCHEDULE"]["severity"] == "low"
    # формальный тип помечен deterministic, модельный — model
    assert by_id["NULLABILITY_UNSPECIFIED"]["detected_by"] == ["deterministic"]
    assert by_id["TIMEZONE_UNDEFINED"]["detected_by"] == ["model"]
    # problem/clarification заполнены из explanation/suggestion
    assert by_id["TIMEZONE_UNDEFINED"]["problem"].startswith("Часовой пояс")


def test_section_path_is_real():
    r = _build()
    by_id = {f["defect_id"]: f for f in r["findings"]}
    # цитата про UTC — в разделе «Алгоритм обработки потока»
    assert by_id["TIMEZONE_UNDEFINED"]["location"]["section_path"] == ["Алгоритм обработки потока"]
    # поле FIELD_A — в разделе «Структура данных»
    assert by_id["NULLABILITY_UNSPECIFIED"]["location"]["section_path"] == ["Структура данных"]


def test_confidence_in_range_and_block_id():
    r = _build()
    for f in r["findings"]:
        assert 0.0 <= f["confidence"] <= 1.0
        assert f["location"]["block_id"].startswith("q-")


def test_empty_findings_valid():
    r = build_review_result(DOC, "d.txt", "txt", [], [], "run-0", "p", "m",
                            {"fragment": "x"}, 0)
    _validate(r)
    assert r["summary"]["returned_findings"] == 0


def test_findings_capped_at_20():
    many = [dict(LLM[0], defect_id="AMBIGUOUS_LOGIC", quote="q%d" % i) for i in range(30)]
    r = build_review_result(DOC, "d.txt", "txt", [], many, "run-1", "p", "m",
                            {"fragment": "x"}, 0)
    assert len(r["findings"]) == 20
    assert r["summary"]["returned_findings"] == 20
    _validate(r)


if __name__ == "__main__":
    test_completed_result_valid_against_contract()
    test_failed_result_valid_against_contract()
    test_severity_and_detected_by_mapping()
    test_section_path_is_real()
    test_confidence_in_range_and_block_id()
    test_empty_findings_valid()
    test_findings_capped_at_20()
    print("все тесты пройдены")
