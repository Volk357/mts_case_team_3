#!/usr/bin/env python3
"""Тесты docreview: вывод валиден по контракту Никиты (JSON-схема v1.0).

Запуск: python test_docreview.py
Схема берётся из contracts/review-result.schema.json ветки Никиты (сохранена
локально в /tmp при разработке; тест ищет её по нескольким путям).
"""
import json
import os
import shutil
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

try:
    import jsonschema
except ImportError:                       # на свежем клоне без зависимости
    jsonschema = None

from docreview import (build_review_result, failed_result,
                       _read_document, UnsupportedBinary, BUDGET,
                       resolve_pack, ReviewPackMissing, _core_path, main,
                       load_model_config, ModelConfigInvalid, _write_artifacts,
                       find_model_config, MODEL_CONFIG_ENV, EXIT_REVIEW_PACK)


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


def test_version_command_reports_pinned_delivery():
    output = StringIO()
    with redirect_stdout(output):
        exit_code = main(["version"])
    assert exit_code == 0
    assert json.loads(output.getvalue()) == {
        "name": "docreview-analysis-core",
        "version": "0.2.0",
        "schema_version": "1.0",
    }


def test_validate_pack_accepts_delivered_pack():
    output = StringIO()
    with redirect_stdout(output):
        exit_code = main(["validate-pack", "--pack", "review-packs/mts-net/0.2"])
    payload = json.loads(output.getvalue())
    assert exit_code == 0
    assert payload["status"] == "valid"
    assert payload["id"] == "mts-net"
    assert payload["version"] == "0.2"


def test_validate_pack_rejects_incomplete_pack():
    directory = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "_tmp_docreview", "incomplete-pack")
    os.makedirs(directory, exist_ok=True)
    pack = os.path.join(directory, "pack.yaml")
    with open(pack, "wb") as source:
        source.write(b'id: broken\nversion: "1.0"\n')
    output = StringIO()
    with redirect_stderr(output):
        exit_code = main(["validate-pack", "--pack", directory])
    assert exit_code == EXIT_REVIEW_PACK
    assert "template.yaml" in output.getvalue()


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


def test_docx_is_extracted_not_rejected():
    """Настоящий .docx ядро теперь разбирает само: таблицы строками с « | »
    и адреса гиперссылок сохраняются. Раньше он читался как бинарный мусор."""
    import zipfile
    W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    path = _tmp("real.docx", b"")
    body = ('<w:p><w:r><w:t>Data Catalog</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>Ссылка: </w:t></w:r><w:hyperlink r:id="r1">'
            '<w:r><w:t>карточка</w:t></w:r></w:hyperlink></w:p>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml",
                   '<?xml version="1.0"?><w:document xmlns:w="%s" xmlns:r="%s">'
                   '<w:body>%s</w:body></w:document>' % (W, R, body))
        z.writestr("word/_rels/document.xml.rels",
                   '<?xml version="1.0"?><Relationships xmlns="http://schemas.'
                   'openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="r1" Type="%s/hyperlink" Target="https://dc/x" '
                   'TargetMode="External"/></Relationships>' % R)
    text, ext, warn, _sha = _read_document(path)
    assert ext == "docx" and "https://dc/x" in text, (ext, text)
    assert warn == []                     # ссылки есть — предупреждения нет


def test_zip_that_is_not_docx_still_rejected():
    """xlsx/pptx — тоже zip, но текста мы из них не извлекаем."""
    import zipfile
    path = _tmp("book.docx", b"")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/workbook.xml", "<x/>")
    try:
        _read_document(path)
        raise AssertionError("ожидали UnsupportedBinary")
    except UnsupportedBinary as e:
        assert "docx" in str(e)


def test_docx_without_links_warns():
    """Если ссылок нет вовсе, замечания об их отсутствии надо читать осторожнее."""
    import zipfile
    W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    path = _tmp("nolinks.docx", b"")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml",
                   '<?xml version="1.0"?><w:document xmlns:w="%s"><w:body>'
                   '<w:p><w:r><w:t>Общие сведения</w:t></w:r></w:p>'
                   '</w:body></w:document>' % W)
    _, ext, warn, _sha = _read_document(path)
    assert ext == "docx" and [w["code"] for w in warn] == ["NO_EXTERNAL_LINKS"]


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
    text, ext, warn, _sha = _read_document(path)
    assert ext == "txt" and warn == [] and "Часовой пояс" in text


def test_extracted_text_under_docx_name_still_works_with_warning():
    # приложение уже извлекло текст, но сохранило под исходным именем
    path = _tmp("extracted.docx", "Общие сведения\n".encode("utf-8"))
    text, ext, warn, _sha = _read_document(path)
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


def _contract_codes():
    """Коды и exit codes из contracts/exit-codes.md — единственный источник правды."""
    import re
    text = open("contracts/exit-codes.md", encoding="utf-8").read()
    codes = {}
    for line in text.splitlines():
        m = re.match(r"\|\s*`?(\d+)`?\s*\|([^|]*)\|", line)
        if not m:
            continue
        exit_code = int(m.group(1))
        for c in re.findall(r"`([A-Z_]+)`", m.group(2)):
            codes.setdefault(c, set()).add(exit_code)
    return codes


def test_core_error_codes_exist_in_contract():
    """Каждый код, который ядро может отдать, обязан быть в контракте и с тем же
    exit code. Раньше ядро отдавало CORE_UNSUPPORTED_FORMAT / CORE_INPUT_UNREADABLE /
    CORE_PROCESS_FAILED — их в каталоге приложения нет, и оно превращало их
    в общий сбой без возможности повтора."""
    import docreview as dr
    contract = _contract_codes()
    assert contract, "не разобрал contracts/exit-codes.md"
    ours = {
        "UNSUPPORTED_DOCUMENT": dr.EXIT_DOCUMENT,
        "DOCUMENT_READ_ERROR": dr.EXIT_DOCUMENT,
        "REVIEW_PACK_NOT_FOUND": dr.EXIT_REVIEW_PACK,
        "REVIEW_PACK_INVALID": dr.EXIT_REVIEW_PACK,
        "MODEL_UNAVAILABLE": dr.EXIT_MODEL,
        "INTERNAL_ERROR": dr.EXIT_INTERNAL,
    }
    for code, exit_code in ours.items():
        assert code in contract, "кода нет в контракте: %s" % code
        assert exit_code in contract[code], (
            "%s: ядро отдаёт exit %d, контракт ждёт %s" % (code, exit_code, contract[code]))


def test_cli_accepts_flags_the_application_sends():
    """process_runner всегда добавляет --artifacts-dir, а по условию ещё
    --model-config и --include-rejected. Без них argparse падал с exit 2."""
    path = _tmp("cli.docx", b"PK\x03\x04\x14\x00 binary")   # быстрый выход по формату
    out = _tmp("cli_out.json", b"")
    rc = main(["analyze", "--file", path, "--run-id", "r", "--output", out,
               "--artifacts-dir", "/tmp/artifacts", "--model-config", "/tmp/model.json",
               "--include-rejected"])
    assert rc == 3, rc            # дошли до чтения документа, а не упали на аргументах
    assert json.load(open(out, encoding="utf-8"))["error"]["code"] == "UNSUPPORTED_DOCUMENT"


def test_resolve_pack_reads_manifest_for_id_and_version():
    """Приложение бракует результат, если id/version не совпали с заданием,
    поэтому источник истины — манифест внутри пакета."""
    pack_id, version, tpl, dfx, glo, warns = resolve_pack("review-packs/mts-net/0.2")
    assert (pack_id, version) == ("mts-net", "0.2"), (pack_id, version)
    assert tpl and dfx and glo and not warns, "правила пакета должны браться целиком"


def test_resolve_pack_accepts_manifest_file_directly():
    pack_id, version, tpl, dfx, glo, warns = resolve_pack("review-packs/mts-net/0.2/pack.yaml")
    assert (pack_id, version) == ("mts-net", "0.2")
    assert tpl and dfx and not warns


def test_resolve_pack_falls_back_to_key_version_layout():
    """Раскладка <pack_key>/<version> — как приложение резолвит локатор."""
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "_tmp_docreview", "requirements", "1.0")
    os.makedirs(d, exist_ok=True)
    pack_id, version, _, _, _, warns = resolve_pack(d)
    assert (pack_id, version) == ("requirements", "1.0"), (pack_id, version)
    assert not warns


def test_resolve_pack_warns_when_version_unknown():
    """Молча подставленная версия = забракованный результат с неочевидной причиной."""
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp_docreview", "plain")
    os.makedirs(d, exist_ok=True)
    pack_id, version, _, _, _, warns = resolve_pack(d)
    assert pack_id == "plain" and version
    assert warns and warns[0]["code"] == "REVIEW_PACK_VERSION_ASSUMED"


def test_resolve_pack_identifier_without_path():
    pack_id, version, tpl, dfx, glo, warns = resolve_pack("mts-net")
    assert pack_id == "mts-net" and version and tpl is None and dfx is None


def test_resolve_pack_missing_path_raises():
    try:
        resolve_pack("/definitely/not/here/pack")
        raise AssertionError("ожидали ReviewPackMissing")
    except ReviewPackMissing:
        pass


def test_core_configs_resolve_outside_working_directory():
    """Приложение запускает ядро со своим cwd, конфиги лежат рядом с ядром."""
    got = _core_path("template.yaml")
    assert os.path.isabs(got) and os.path.isfile(got), got


def test_model_config_is_the_channel_for_endpoint():
    """ProcessRunner вычищает окружение дочернего процесса, поэтому OLLAMA_URL
    из окружения приложения до ядра не доходит: единственный канал — этот файл."""
    path = _tmp("model.yaml", b"base_url: http://10.1.2.3:11434/api/chat\nmodel: qwen3:30b-a3b\nnum_ctx: 4096\n")
    conf = load_model_config(path)
    assert conf["url"] == "http://10.1.2.3:11434/api/chat"
    assert conf["model"] == "qwen3:30b-a3b" and conf["num_ctx"] == 4096


def test_model_config_missing_file_is_reported():
    try:
        load_model_config("/definitely/not/here/model.yaml")
        raise AssertionError("ожидали ModelConfigInvalid")
    except ModelConfigInvalid:
        pass


def test_rejected_candidates_go_to_artifacts_not_result():
    """Контракт: отклонённые кандидаты только в debug-артефактах."""
    class A:
        artifacts_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "_tmp_docreview", "art")
        include_rejected = True
    llm = {"found_raw": 3, "verified": 1, "rejected_count": 2,
           "reject_reasons": {"quote_not_found": 2},
           "rejected": [{"quote": "нет такой строки"}], "capped": []}
    result = {"run_id": "r-1"}
    _write_artifacts(A, llm, [], result)
    got = json.load(open(os.path.join(A.artifacts_dir, "analysis-debug.json"),
                         encoding="utf-8"))
    assert got["counters"]["rejected_count"] == 2
    assert got["rejected"] and got["run_id"] == "r-1"


def test_artifacts_skipped_without_flag():
    class A:
        artifacts_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "_tmp_docreview", "art2")
        include_rejected = False
    _write_artifacts(A, {"rejected": [{"quote": "x"}]}, [], {"run_id": "r-2"})
    got = json.load(open(os.path.join(A.artifacts_dir, "analysis-debug.json"),
                         encoding="utf-8"))
    assert "rejected" not in got


def test_pack_manifest_must_declare_id_and_version():
    """Манифест объявлен источником истины — значит неполный манифест это ошибка,
    а не повод тихо достроить идентичность из пути."""
    from docreview import ReviewPackInvalid
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp_docreview", "bad")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "pack.yaml"), "w", encoding="utf-8") as fh:
        fh.write("id: only-id\n")            # version отсутствует
    try:
        resolve_pack(d)
        raise AssertionError("ожидали ReviewPackInvalid")
    except ReviewPackInvalid as e:
        assert "version" in str(e), e


def test_model_config_rejects_non_numeric_values():
    """num_ctx: not-an-int должен давать MODEL_CONFIG_INVALID (exit 5),
    а не общий INTERNAL_ERROR (exit 7)."""
    path = _tmp("bad_model.yaml", b"base_url: http://x/api\nnum_ctx: not-an-int\n")
    try:
        load_model_config(path)
        raise AssertionError("ожидали ModelConfigInvalid")
    except ModelConfigInvalid as e:
        assert "num_ctx" in str(e), e
    # дробное, булево, отрицательное, список — всё это «написано не то, что имели в виду»
    for body, why in ((b"base_url: http://x/api\ntimeout: -5\n", "отрицательное"),
                      (b"base_url: http://x/api\nnum_ctx: 1.5\n", "дробное"),
                      (b"base_url: http://x/api\ntimeout: true\n", "булево"),
                      (b"base_url: http://x/api\nnum_ctx: [1]\n", "список")):
        path2 = _tmp("bad_model_%s.yaml" % abs(hash(body)), body)
        try:
            load_model_config(path2)
            raise AssertionError("ожидали ModelConfigInvalid: %s" % why)
        except ModelConfigInvalid:
            pass
    # корректные значения по-прежнему принимаются, в том числе строкой
    ok = load_model_config(_tmp("ok_model.yaml",
                                b"base_url: http://x/api\nnum_ctx: '8192'\n"))
    assert ok["num_ctx"] == 8192


def test_broken_pack_glossary_is_pack_error_not_internal():
    """Глоссарий ядра при сломанном yaml откатывается на константу (его правит
    аналитик), глоссарий ПАКЕТА — часть версионируемого артефакта: ошибка."""
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp_docreview", "gl")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "pack.yaml"), "w", encoding="utf-8") as fh:
        fh.write("id: gl\nversion: '1.0'\n")
    for name, body in (("template.yaml", "sections: []\n"),
                       ("defects.yaml", "defects: []\n"),
                       ("glossary.yaml", "terms: [a: : b\n")):     # битый yaml
        with open(os.path.join(d, name), "w", encoding="utf-8") as fh:
            fh.write(body)
    out = _tmp("gl_out.json", b"")
    doc = _tmp("gl_doc.txt", "Общие сведения\nЧасовой пояс: UTC\n".encode("utf-8"))
    rc = main(["analyze", "--file", doc, "--run-id", "gl", "--pack", d, "--output", out])
    assert rc == 4, rc
    assert json.load(open(out, encoding="utf-8"))["error"]["code"] == "REVIEW_PACK_INVALID"


def test_model_config_lookup_order():
    """Флаг worker имеет приоритет; запасные источники нужны прямому CLI."""
    explicit = _tmp("explicit.yaml", b"base_url: http://explicit/api\n")
    from_env = _tmp("env.yaml", b"base_url: http://env/api\n")
    old = os.environ.get(MODEL_CONFIG_ENV)
    try:
        os.environ[MODEL_CONFIG_ENV] = from_env
        assert find_model_config(explicit) == explicit      # флаг важнее всего
        assert find_model_config(None) == from_env          # затем окружение
        os.environ.pop(MODEL_CONFIG_ENV)
        beside = find_model_config(None)                    # затем рядом с ядром
        core_default = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "model-config.yaml")
        assert beside == (core_default if os.path.isfile(core_default) else None)
    finally:
        if old is None:
            os.environ.pop(MODEL_CONFIG_ENV, None)
        else:
            os.environ[MODEL_CONFIG_ENV] = old


def test_document_sha256_is_of_file_bytes_not_text():
    """Приложение сверяет document.sha256 с хешем ЗАГРУЖЕННОГО ФАЙЛА и бракует
    результат при расхождении (review_result.py: «result document SHA-256 does
    not match Document»). Проверяем на .docx: там хеш файла и хеш извлечённого
    текста РАЗНЫЕ по построению, поэтому подмена одного другим сразу видна.
    На .txt дефект не воспроизводится — байты совпадают с текстом."""
    import hashlib as _h
    import zipfile
    W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    path = _tmp("hashed.docx", b"")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml",
                   '<?xml version="1.0"?><w:document xmlns:w="%s"><w:body>'
                   '<w:p><w:r><w:t>Часовой пояс: UTC</w:t></w:r></w:p>'
                   '</w:body></w:document>' % W)
    raw = open(path, "rb").read()
    text, ext, _, digest = _read_document(path)

    assert ext == "docx"
    assert digest == _h.sha256(raw).hexdigest(), "хеш обязан быть от байтов файла"
    assert digest != _h.sha256(text.encode("utf-8")).hexdigest(), \
        "тест бессмысленен, если хеши совпадают"

    result = build_review_result(text, "hashed.docx", ext, [], [], "r", "p", "m",
                                 {"fragment": "x"}, 0, document_sha256=digest)
    assert result["document"]["sha256"] == digest
    _validate(result)


def test_formal_findings_with_missing_quote_are_dropped_with_a_warning():
    """Тезис «замечание без совпадения с текстом отбрасывается» до этого держался
    на построении проверок: verify_quotes вызывался только из самостоятельного CLI
    и там лишь печатал предупреждение, а боевой путь брал findings напрямую.
    Проверяем сам фильтр, а не построение: подсовываем находку с цитатой, которой
    в документе нет."""
    from docreview import _verified_formal

    text = "Часовой пояс не указан.\nОбновление ежедневно."
    good = {"defect_id": "TIMEZONE_UNDEFINED", "quote": "Часовой пояс не указан."}
    invented = {"defect_id": "NO_SCHEDULE", "quote": "Регламент обновления — раз в час."}
    warnings = []

    kept = _verified_formal({"findings": [good, invented]}, text, warnings)

    assert [f["quote"] for f in kept] == [good["quote"]]
    assert [w["code"] for w in warnings] == ["FORMAL_QUOTE_NOT_FOUND"]
    assert "1" in warnings[0]["message"]


def test_formal_findings_present_in_text_pass_untouched():
    """Цена фильтра измерена и равна нулю: на 5 synth-документах, их чистых
    версиях, извлечённом .docx и трёх реальных документах ни одна из 42 находок
    не отсеивается. Здесь закрепляем, что при совпадении цитат фильтр не трогает
    ни состав, ни порядок и не добавляет предупреждений."""
    from docreview import _verified_formal

    text = "Часовой пояс не указан.\nФильтрация не описана."
    findings = [{"defect_id": "TIMEZONE_UNDEFINED", "quote": "Часовой пояс не указан."},
                {"defect_id": "NO_FILTER_DESCRIPTION", "quote": "Фильтрация не описана."}]
    warnings = []

    kept = _verified_formal({"findings": list(findings)}, text, warnings)

    assert kept == findings
    assert warnings == []


if __name__ == "__main__":
    test_completed_result_valid_against_contract()
    test_failed_result_valid_against_contract()
    test_severity_and_detected_by_mapping()
    test_section_path_is_real()
    test_confidence_in_range_and_block_id()
    test_empty_findings_valid()
    test_findings_capped_at_20()
    test_docx_is_extracted_not_rejected()
    test_document_sha256_is_of_file_bytes_not_text()
    test_formal_findings_with_missing_quote_are_dropped_with_a_warning()
    test_formal_findings_present_in_text_pass_untouched()
    test_zip_that_is_not_docx_still_rejected()
    test_docx_without_links_warns()
    test_pdf_and_ole_rejected()
    test_binary_renamed_to_txt_rejected()
    test_txt_still_read_without_warnings()
    test_extracted_text_under_docx_name_still_works_with_warning()
    test_unsupported_format_failed_result_valid_against_contract()
    test_core_error_codes_exist_in_contract()
    test_cli_accepts_flags_the_application_sends()
    test_resolve_pack_reads_manifest_for_id_and_version()
    test_resolve_pack_accepts_manifest_file_directly()
    test_resolve_pack_falls_back_to_key_version_layout()
    test_resolve_pack_warns_when_version_unknown()
    test_resolve_pack_identifier_without_path()
    test_model_config_is_the_channel_for_endpoint()
    test_model_config_missing_file_is_reported()
    test_model_config_lookup_order()
    test_rejected_candidates_go_to_artifacts_not_result()
    test_artifacts_skipped_without_flag()
    test_pack_manifest_must_declare_id_and_version()
    test_model_config_rejects_non_numeric_values()
    test_broken_pack_glossary_is_pack_error_not_internal()
    test_resolve_pack_missing_path_raises()
    test_core_configs_resolve_outside_working_directory()
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
