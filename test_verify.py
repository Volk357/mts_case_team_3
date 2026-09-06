#!/usr/bin/env python3
"""
Тесты слоя семантической верификации (semantic verdict).

Что этот слой делает и что проверяется здесь.

Аудит 06.09.2026, пункты 3, 4 и 5: замечание модели попадало на экран
после проверки цитаты, без отдельного суждения о том, справедливо ли оно;
и придумывала, и подтверждала его одна и та же модель одним и тем же
подходом. Слой добавляет состояние Semantic verdict между Evidence check
и Accepted finding.

Модель здесь НЕ вызывается ни в одном тесте: `ask_verifier` подменяется.
Проверяется механика — разбор вердиктов, группировка по фрагментам,
поведение режимов, устойчивость к мусору в ответе. Качество суждений
модели механикой не проверяется и проверено быть не может: это замер
на документах, он в журнале.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import run_review                                              # noqa: E402
import docreview                                               # noqa: E402

PACK = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    "review-packs", "mts-net", "0.2")

DOC = "\n\n".join([
    "1. Бизнес-требования\nВитрина строится по данным источника ежедневно.",
    "2. Структура данных\nFIELD_ID | bigint | Идентификатор записи.",
    "3. Требования к результату\nСрок хранения данных не определён.",
])


def _finding(quote, defect_id="X", explanation="почему это проблема"):
    return {"quote": quote, "defect_id": defect_id, "severity": "medium",
            "explanation": explanation, "suggestion": "что уточнить"}


class _Verifier:
    """Подменённый верификатор: отдаёт заготовленные вердикты и считает вызовы."""

    def __init__(self, plan):
        self.plan = plan            # функция (prompt) -> ответ модели
        self.calls = []

    def __call__(self, prompt):
        self.calls.append(prompt)
        return self.plan(prompt)


def _with_verifier(plan, fn):
    original = run_review.ask_verifier
    stub = _Verifier(plan)
    run_review.ask_verifier = stub
    try:
        return fn(), stub
    finally:
        run_review.ask_verifier = original


# --- 1. Разбор вердиктов --------------------------------------------------

def test_verdicts_are_attached_to_the_right_findings():
    findings = [_finding("Витрина строится по данным источника ежедневно."),
                _finding("Срок хранения данных не определён.")]

    def plan(prompt):
        return [{"id": 1, "verdict": "reject", "reason": "правило 1: уже есть"},
                {"id": 2, "verdict": "accept", "reason": "срок не назван"}]

    (result, _), _ = _with_verifier(plan, lambda: (
        run_review.verify_semantics(findings, DOC), None))
    assert result[0]["_verdict"]["verdict"] == "reject"
    assert "правило 1" in result[0]["_verdict"]["reason"]
    assert result[1]["_verdict"]["verdict"] == "accept"


def test_string_and_dotted_ids_are_understood():
    """Модель возвращает id то числом, то строкой, изредка «3.».

    Потерянный вердикт в enforcing означает, что замечание пройдёт
    непроверенным, поэтому разбор терпимый к форме, но не к смыслу.
    """
    findings = [_finding("Витрина строится по данным источника ежедневно."),
                _finding("FIELD_ID | bigint | Идентификатор записи.")]

    def plan(prompt):
        return [{"id": "1.", "verdict": "reject", "reason": "r"},
                {"id": "2", "verdict": "accept", "reason": "a"}]

    (result, _), _ = _with_verifier(plan, lambda: (
        run_review.verify_semantics(findings, DOC), None))
    assert result[0]["_verdict"]["verdict"] == "reject"
    assert result[1]["_verdict"]["verdict"] == "accept"


def test_garbage_from_verifier_leaves_findings_unverified():
    """Мусор не должен молча превращаться в «принято».

    Проверяется каждый вид порчи отдельно: индекс за границей, чужой
    вердикт, не тот тип, ответ не списком.
    """
    cases = [
        [{"id": 99, "verdict": "reject", "reason": "r"}],     # вне диапазона
        [{"id": 1, "verdict": "maybe", "reason": "r"}],       # чужой вердикт
        [{"id": None, "verdict": "reject", "reason": "r"}],   # нет индекса
        [{"id": True, "verdict": "reject", "reason": "r"}],   # bool, не число
        ["строка вместо объекта"],
        [],
        {"не": "список"},
    ]
    for payload in cases:
        findings = [_finding("Срок хранения данных не определён.")]
        (result, _), _ = _with_verifier(lambda p, r=payload: r, lambda: (
            run_review.verify_semantics(findings, DOC), None))
        assert "_verdict" not in result[0], payload


def test_findings_are_grouped_into_batches_not_one_call_each():
    """Партиями, а не по вызову на замечание: иначе демонстрация встанет."""
    findings = [_finding("Срок хранения данных не определён.",
                         explanation="вариант %d" % i) for i in range(20)]
    policy = dict(run_review.DEFAULT_POLICY,
                  verification={"mode": "advisory", "batch_size": 8})
    (_, _), stub = _with_verifier(lambda p: [], lambda: (
        run_review.verify_semantics(findings, DOC, policy=policy), None))
    # 20 замечаний одной цитаты → один фрагмент → 3 партии по 8.
    assert len(stub.calls) == 3, len(stub.calls)


def test_verifier_sees_fragment_and_not_the_suggestion():
    """Верификатору не показывают собственную рекомендацию генератора.

    Иначе он оценивает связку «проблема + её решение», которая выглядит
    убедительно просто потому, что написана согласованно.
    """
    findings = [_finding("Срок хранения данных не определён.")]
    findings[0]["suggestion"] = "УНИКАЛЬНАЯ_РЕКОМЕНДАЦИЯ_ГЕНЕРАТОРА"
    (_, _), stub = _with_verifier(lambda p: [], lambda: (
        run_review.verify_semantics(findings, DOC), None))
    prompt = stub.calls[0]
    assert "УНИКАЛЬНАЯ_РЕКОМЕНДАЦИЯ_ГЕНЕРАТОРА" not in prompt
    assert "Срок хранения данных не определён." in prompt
    # Контекст цитаты подан, и это тот фрагмент, где она лежит.
    assert "3. Требования к результату" in prompt
    assert "почему это проблема" in prompt


def test_empty_input_does_not_call_the_model():
    (_, _), stub = _with_verifier(lambda p: [], lambda: (
        run_review.verify_semantics([], DOC), None))
    assert stub.calls == []


def test_model_supplied_verdict_is_stripped_on_entry():
    """Модель может вернуть собственный `_verdict` — он не суждение.

    Блокер ревью: схема ответа лишние ключи не запрещает, поэтому находка
    с подставленным `_verdict` уходила бы в выдачу как `accepted`, не пройдя
    никакой проверки, — в том числе при verification.mode = off.
    Снимается на входе, в `verify`.
    """
    poisoned = [{"quote": "Срок хранения данных не определён.",
                 "defect_id": "X", "severity": "medium",
                 "explanation": "e", "suggestion": "s",
                 "_verdict": {"verdict": "accept", "reason": "самоназначено"}}]
    kept, _ = run_review.verify(poisoned, DOC, set())
    assert kept, "находка должна остаться"
    assert "_verdict" not in kept[0], kept[0]

    result = docreview.build_review_result(
        DOC, "d.txt", "T", [], kept, "r-1", ("mts-net", "0.2"), "m",
        {"fragment": "dict2"}, 1.0)
    assert result["findings"][0]["verification"]["state"] == "not_verified"


def test_malformed_numeric_ids_are_not_misattributed():
    """`-1` и `1e2` не должны привязываться к чужому кандидату.

    Блокер ревью: прежний разбор вычищал все нецифровые символы, и «-1»
    становилось первым замечанием, а «1e2» — двенадцатым. В enforcing
    это удаляло не то замечание.
    """
    for bad in ("-1", "1e2", "0", "abc", "", "1 2", "1.5"):
        findings = [_finding("Срок хранения данных не определён."),
                    _finding("FIELD_ID | bigint | Идентификатор записи.")]
        (result, _), _ = _with_verifier(
            lambda p, b=bad: [{"id": b, "verdict": "reject", "reason": "r"}],
            lambda: (run_review.verify_semantics(findings, DOC), None))
        assert all("_verdict" not in f for f in result), (bad, result)
    # А корректные формы по-прежнему работают.
    findings = [_finding("Срок хранения данных не определён.")]
    (result, _), _ = _with_verifier(
        lambda p: [{"id": "1.", "verdict": "reject", "reason": "r"}],
        lambda: (run_review.verify_semantics(findings, DOC), None))
    assert result[0]["_verdict"]["verdict"] == "reject"


def test_verifier_network_failure_does_not_lose_findings():
    """Сбой верификатора не уносит уже найденное.

    Блокер ревью: сетевая ошибка пробрасывалась наружу и отменяла проходы
    поиска, хотя 05.09 отдельной правкой добивались, чтобы при отказе
    модели результат не терялся.
    """
    import requests

    def boom(*args, **kwargs):
        raise requests.exceptions.ConnectionError("сеть недоступна")

    findings = [_finding("Срок хранения данных не определён."),
                _finding("FIELD_ID | bigint | Идентификатор записи.")]
    # Ломаем именно сетевой вызов, а не подменяем ask_verifier целиком:
    # проверяется обработка ошибки ВНУТРИ ask_verifier.
    orig_post = run_review.requests.post
    run_review.requests.post = boom
    try:
        result = run_review.verify_semantics(findings, DOC)
    finally:
        run_review.requests.post = orig_post
    assert len(result) == 2, "находки должны остаться"
    assert all("_verdict" not in f for f in result)


def test_duplicate_ids_keep_the_first_verdict():
    """Повторный id: выигрывает первый, счётчик не растёт дважды.

    Блокер ревью: раньше выигрывал последний, и противоречивый дубликат
    мог перевернуть решение, а статистика показывала больше проверенных,
    чем есть замечаний.
    """
    findings = [_finding("Срок хранения данных не определён."),
                _finding("FIELD_ID | bigint | Идентификатор записи.")]

    def plan(prompt):
        return [{"id": 1, "verdict": "accept", "reason": "первый"},
                {"id": 1, "verdict": "reject", "reason": "дубликат"}]

    (result, _), _ = _with_verifier(plan, lambda: (
        run_review.verify_semantics(findings, DOC), None))
    assert result[0]["_verdict"]["verdict"] == "accept", result[0]["_verdict"]
    assert result[0]["_verdict"]["reason"] == "первый"
    # Второе замечание осталось без вердикта, а не «проверено» по чужому.
    assert "_verdict" not in result[1]


# --- 2. Режимы политики ---------------------------------------------------

def _run_full_with(mode, verdict_plan):
    """run_full с подменёнными проходами: модель не вызывается нигде."""
    quotes = ["Витрина строится по данным источника ежедневно.",
              "FIELD_ID | bigint | Идентификатор записи.",
              "Срок хранения данных не определён."]
    findings = [_finding(q, defect_id="TYPE_%d" % i)
                for i, q in enumerate(quotes)]
    stub = {"findings": findings, "fragments": 3, "total_seconds": 0.0,
            "found_raw": 3, "verified": 3, "rejected_count": 0,
            "reject_reasons": {}, "rejected": [], "truncated_chars": 0}
    empty = dict(stub, findings=[], found_raw=0, verified=0)
    policy = dict(run_review.DEFAULT_POLICY,
                  verification={"mode": mode, "batch_size": 8})

    orig_run, orig_global = run_review.run, run_review.run_global
    run_review.run = lambda *a, **k: dict(stub)
    run_review.run_global = lambda *a, **k: dict(empty)
    try:
        (result, _), stubv = _with_verifier(verdict_plan, lambda: (
            run_review.run_full(DOC, [], "<T>", set(), "<K>",
                                frag_mode="dict2", policy=policy), None))
        return result, stubv
    finally:
        run_review.run, run_review.run_global = orig_run, orig_global


def test_advisory_marks_but_does_not_drop():
    """advisory: вердикт есть, выдача не меняется.

    Это и есть причина, по которой режим стоит по умолчанию: цену
    верификации нельзя измерить, если она сразу меняет то, что измеряют.
    """
    plan = lambda p: [{"id": i + 1, "verdict": "reject", "reason": "r"}
                      for i in range(8)]
    result, _ = _run_full_with("advisory", plan)
    assert len(result["findings"]) == 3, len(result["findings"])
    assert result["verifier_rejected"] == 0
    assert result["verifier_would_reject"] == 3
    assert all(f["_verdict"]["verdict"] == "reject" for f in result["findings"])


def test_enforcing_drops_rejected():
    plan = lambda p: [{"id": 1, "verdict": "reject", "reason": "r"},
                      {"id": 2, "verdict": "accept", "reason": "a"},
                      {"id": 3, "verdict": "accept", "reason": "a"}]
    result, _ = _run_full_with("enforcing", plan)
    assert len(result["findings"]) == 2, len(result["findings"])
    assert result["verifier_rejected"] == 1
    assert len(result["verifier_dropped"]) == 1
    assert all(f["_verdict"]["verdict"] == "accept" for f in result["findings"])


def test_enforcing_keeps_unverified_findings():
    """Без вердикта — не отбрасываем: молчание верификатора не приговор.

    Иначе сбой модели или невалидный json тихо выкашивали бы выдачу,
    и это выглядело бы как «дефектов нет».
    """
    result, _ = _run_full_with("enforcing", lambda p: [])
    assert len(result["findings"]) == 3
    assert result["verifier_rejected"] == 0


def test_off_does_not_call_the_verifier():
    result, stub = _run_full_with("off", lambda p: [])
    assert stub.calls == []
    assert len(result["findings"]) == 3
    assert result["verified_count"] == 0


# --- 3. Вердикт доходит до результата ------------------------------------

def test_verification_state_reaches_the_result():
    findings = [dict(_finding("Срок хранения данных не определён."),
                     _verdict={"verdict": "reject", "reason": "правило 3"}),
                dict(_finding("FIELD_ID | bigint | Идентификатор записи.",
                              defect_id="Y"),
                     _verdict={"verdict": "accept", "reason": "нет типа"}),
                _finding("Витрина строится по данным источника ежедневно.",
                         defect_id="Z")]
    result = docreview.build_review_result(
        DOC, "d.txt", "T", [], findings, "r-1", ("mts-net", "0.2"), "m",
        {"fragment": "dict2"}, 1.0)
    states = {f["defect_id"]: f["verification"]["state"] for f in result["findings"]}
    assert states["X"] == "rejected", states
    assert states["Y"] == "accepted", states
    assert states["Z"] == "not_verified", states
    reasons = {f["defect_id"]: f["verification"]["reason"] for f in result["findings"]}
    assert reasons["X"] == "правило 3"


def test_deterministic_findings_are_not_applicable():
    """Слой правил верификатором не разбирается — он и есть независимая проверка.

    Отдавать его находки на суд той же модели значило бы вернуть ту самую
    корреляцию, ради ухода от которой слой заведён.
    """
    formal = [_finding("Срок хранения данных не определён.", defect_id="RULE")]
    result = docreview.build_review_result(
        DOC, "d.txt", "T", formal, [], "r-1", ("mts-net", "0.2"), "m",
        {"fragment": "dict2"}, 1.0)
    v = result["findings"][0]["verification"]
    assert v["state"] == "not_applicable", v
    assert result["findings"][0]["detected_by"] == ["deterministic"]


def test_result_with_verification_passes_the_contract():
    from contracts.validate_contract import validate_review_result
    findings = [dict(_finding("Срок хранения данных не определён."),
                     _verdict={"verdict": "reject", "reason": "r"})]
    result = docreview.build_review_result(
        DOC, "d.txt", "T", [], findings, "run-1", ("mts-net", "0.2"),
        "qwen3:30b-a3b", {"fragment": "dict2", "global": "global"}, 12.0,
        document_sha256="a" * 64)
    validate_review_result(result)


def test_internal_verdict_field_does_not_leak_outside():
    """`_verdict` — внутреннее поле, наружу идёт только `verification`."""
    import json
    findings = [dict(_finding("Срок хранения данных не определён."),
                     _verdict={"verdict": "reject", "reason": "r"})]
    result = docreview.build_review_result(
        DOC, "d.txt", "T", [], findings, "r-1", ("mts-net", "0.2"), "m",
        {"fragment": "dict2"}, 1.0)
    assert "_verdict" not in json.dumps(result, ensure_ascii=False)


# --- 4. Политика верификации ---------------------------------------------

def test_pack_declares_verification():
    policy = run_review.load_policy(os.path.join(PACK, "policy.yaml"))
    assert policy["verification"] == {"mode": "advisory", "batch_size": 8}


def test_verification_is_required_in_policy_file():
    """Тот же принцип, что и у остальной политики: файл есть — он полный."""
    fd, path = tempfile.mkstemp(suffix=".yaml")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("ceiling: 20\nbias: recall\n"
                 "prompt:\n  bias: b\n  fragment_quota: f\n  document_quota: d\n")
    try:
        run_review.load_policy(path)
    except run_review.PolicyInvalid as e:
        assert "verification" in str(e), str(e)
    else:
        raise AssertionError("политика без verification принята")
    finally:
        os.unlink(path)


def test_bad_verification_values_are_rejected():
    bodies = [
        ("verification:\n  mode: whatever\n  batch_size: 8\n", "mode"),
        ("verification:\n  mode: advisory\n  batch_size: 0\n", "batch_size"),
        ("verification:\n  mode: advisory\n  batch_size: true\n", "batch_size"),
        ("verification:\n  mode: advisory\n", "batch_size"),
        ("verification:\n  mode: advisory\n  batch_size: 8\n  extra: 1\n", "extra"),
        ("verification: строка\n", "verification"),
    ]
    head = ("ceiling: 20\nbias: recall\n"
            "prompt:\n  bias: b\n  fragment_quota: f\n  document_quota: d\n")
    for body, expected in bodies:
        fd, path = tempfile.mkstemp(suffix=".yaml")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(head + body)
        try:
            run_review.load_policy(path)
        except run_review.PolicyInvalid as e:
            assert expected in str(e), (body, str(e))
        else:
            raise AssertionError("принято: %s" % body)
        finally:
            os.unlink(path)


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    for t in TESTS:
        t()
        print("ok  %s" % t.__name__)
    print("\n%d passed" % len(TESTS))
