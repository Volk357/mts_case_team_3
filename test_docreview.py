#!/usr/bin/env python3
"""Тесты docreview: вывод валиден по контракту Никиты (JSON-схема v1.0).

Запуск: python test_docreview.py
Схема берётся из contracts/review-result.schema.json ветки Никиты (сохранена
локально в /tmp при разработке; тест ищет её по нескольким путям).
"""
import json
import os
import shutil

try:
    import jsonschema
except ImportError:                       # на свежем клоне без зависимости
    jsonschema = None

from docreview import (build_review_result, failed_result,
                       _read_document, UnsupportedBinary, BUDGET)


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


def _tmp(name, data):
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp_docreview")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, name)
    with open(path, "wb") as fh:
        fh.write(data)
    return path


def test_docx_rejected_not_parsed_as_text():
    # реальный .docx — zip-контейнер; раньше читался как мусор и давал
    # «успешный» ответ с замечанием на строке PK..[Content_Types].xml
    path = _tmp("d.docx", b"PK\x03\x04\x14\x00\x00\x00[Content_Types].xml\xd0\xa1")
    try:
        _read_document(path)
        raise AssertionError("двоичный docx должен быть отбит")
    except UnsupportedBinary as e:
        assert "docx" in str(e)


def test_pdf_and_ole_rejected():
    for name, head in (("d.pdf", b"%PDF-1.7\n"), ("d.doc", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")):
        try:
            _read_document(_tmp(name, head + b"\x00\x01binary"))
            raise AssertionError(name + " должен быть отбит")
        except UnsupportedBinary:
            pass


def test_binary_renamed_to_txt_rejected():
    # проверка по содержимому, а не по расширению
    path = _tmp("renamed.txt", b"PK\x03\x04\x14\x00 whatever")
    try:
        _read_document(path)
        raise AssertionError("переименованный docx должен быть отбит")
    except UnsupportedBinary:
        pass


def test_txt_still_read_without_warnings():
    path = _tmp("ok.txt", "Общие сведения\nЧасовой пояс: UTC\n".encode("utf-8"))
    text, ext, warn = _read_document(path)
    assert ext == "txt" and warn == [] and "Часовой пояс" in text


def test_extracted_text_under_docx_name_still_works_with_warning():
    # приложение уже извлекло текст, но сохранило под исходным именем
    path = _tmp("extracted.docx", "Общие сведения\n".encode("utf-8"))
    text, ext, warn = _read_document(path)
    assert ext == "docx" and [w["code"] for w in warn] == ["PARSER_FALLBACK"]
    assert "Общие сведения" in text


def test_unsupported_format_failed_result_valid_against_contract():
    fr = failed_result("run-10", "CORE_UNSUPPORTED_FORMAT", "read",
                       "Файл в формате docx", False)
    assert fr["status"] == "failed" and fr["error"]["retriable"] is False
    _validate(fr)


def _f(did, sev, q, det_layer=False, merged=1):
    d = {"defect_id": did, "quote": q, "explanation": "почему", "suggestion": "как",
         "severity": sev}
    if merged > 1:
        d["merged_count"] = merged
    return d


def test_high_not_dropped_by_many_formal_findings():
    # R11: раньше был срез по позиции — 15 формальных medium вытесняли все high модели
    formal = [_f("PLACEHOLDER_LEFT", "medium", "q%d" % i) for i in range(15)]
    llm = [_f("INTERNAL_CONTRADICTION", "high", "h%d" % i) for i in range(8)]
    r = build_review_result(DOC, "d.txt", "txt", formal, llm, "run-1", "p", "m",
                            {"fragment": "x"}, 0)
    assert len(r["findings"]) == BUDGET
    assert sum(1 for f in r["findings"] if f["severity"] == "high") == 8
    _validate(r)


def test_deterministic_not_displaced_by_model_medium():
    formal = [_f("NULLABILITY_UNSPECIFIED", "medium", "d%d" % i) for i in range(5)]
    llm = [_f("AMBIGUOUS_LOGIC", "medium", "m%d" % i, merged=3) for i in range(25)]
    r = build_review_result(DOC, "d.txt", "txt", formal, llm, "run-2", "p", "m",
                            {"fragment": "x"}, 0)
    det = [f for f in r["findings"] if f["detected_by"] == ["deterministic"]]
    assert len(det) == 5, "детерминированные не должны вытесняться модельными"
    assert len(r["findings"]) == BUDGET


def test_high_first_in_output_order():
    formal = [_f("PLACEHOLDER_LEFT", "medium", "q1")]
    llm = [_f("AMBIGUOUS_LOGIC", "low", "l1"), _f("INTERNAL_CONTRADICTION", "high", "h1")]
    r = build_review_result(DOC, "d.txt", "txt", formal, llm, "run-3", "p", "m",
                            {"fragment": "x"}, 0)
    assert r["findings"][0]["severity"] == "high"


def test_nothing_lost_when_under_budget():
    formal = [_f("PLACEHOLDER_LEFT", "medium", "q1")]
    llm = [_f("AMBIGUOUS_LOGIC", "low", "l1"), _f("NO_SCHEDULE", "medium", "m1")]
    r = build_review_result(DOC, "d.txt", "txt", formal, llm, "run-4", "p", "m",
                            {"fragment": "x"}, 0)
    assert len(r["findings"]) == 3
    assert {f["quote"] for f in r["findings"]} == {"q1", "l1", "m1"}


def test_ceiling_holds_when_protected_alone_exceeds_it():
    formal = [_f("PLACEHOLDER_LEFT", "medium", "q%d" % i) for i in range(30)]
    r = build_review_result(DOC, "d.txt", "txt", formal, [], "run-5", "p", "m",
                            {"fragment": "x"}, 0)
    assert len(r["findings"]) == BUDGET     # схема контракта: maxItems 20
    _validate(r)


def test_more_confident_medium_wins_the_last_slot():
    formal = []
    llm = ([_f("INTERNAL_CONTRADICTION", "high", "h%d" % i) for i in range(19)]
           + [_f("AMBIGUOUS_LOGIC", "medium", "слабое замечание модели"),
              _f("NO_SCHEDULE", "medium", "уверенное замечание модели", merged=4)])
    r = build_review_result(DOC, "d.txt", "txt", formal, llm, "run-6", "p", "m",
                            {"fragment": "x"}, 0)
    quotes = [f["quote"] for f in r["findings"]]
    assert "уверенное замечание модели" in quotes
    assert "слабое замечание модели" not in quotes


def test_output_order_is_global_not_protected_first():
    # блокер круга 1: детерминированный low стоял выше модельного medium
    formal = [_f("VAGUE_WORDING", "low", "детерминированный low")]
    llm = [_f("AMBIGUOUS_LOGIC", "medium", "модельный medium")]
    r = build_review_result(DOC, "d.txt", "txt", formal, llm, "run-7", "p", "m",
                            {"fragment": "x"}, 0)
    assert [f["quote"] for f in r["findings"]] == ["модельный medium",
                                                   "детерминированный low"]


def test_protection_still_decides_who_survives():
    # порядок общий, но отбор прежний: детерминированный low не вытесняется
    formal = [_f("VAGUE_WORDING", "low", "детерминированный low")]
    llm = [_f("AMBIGUOUS_LOGIC", "medium", "m%d" % i, merged=3) for i in range(25)]
    r = build_review_result(DOC, "d.txt", "txt", formal, llm, "run-8", "p", "m",
                            {"fragment": "x"}, 0)
    quotes = [f["quote"] for f in r["findings"]]
    assert "детерминированный low" in quotes and len(quotes) == BUDGET
    assert quotes[-1] == "детерминированный low"      # выжил, но в хвосте выдачи


if __name__ == "__main__":
    test_completed_result_valid_against_contract()
    test_failed_result_valid_against_contract()
    test_severity_and_detected_by_mapping()
    test_section_path_is_real()
    test_confidence_in_range_and_block_id()
    test_empty_findings_valid()
    test_findings_capped_at_20()
    test_docx_rejected_not_parsed_as_text()
    test_pdf_and_ole_rejected()
    test_binary_renamed_to_txt_rejected()
    test_txt_still_read_without_warnings()
    test_extracted_text_under_docx_name_still_works_with_warning()
    test_unsupported_format_failed_result_valid_against_contract()
    test_high_not_dropped_by_many_formal_findings()
    test_deterministic_not_displaced_by_model_medium()
    test_high_first_in_output_order()
    test_nothing_lost_when_under_budget()
    test_ceiling_holds_when_protected_alone_exceeds_it()
    test_more_confident_medium_wins_the_last_slot()
    test_output_order_is_global_not_protected_first()
    test_protection_still_decides_who_survives()
    shutil.rmtree(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "_tmp_docreview"), ignore_errors=True)
    print("все тесты пройдены")
