#!/usr/bin/env python3
"""
Тесты жизненного цикла правил (пункт 7 аудита).

Что было. Аудит: «not_tested и даже rejected правила продолжают работать.
Нужны состояния: draft → calibrating → active → deprecated».

Претензия подтвердилась буквально: в `defects.yaml` было поле `validated`
со значениями `not_tested` (18 типов из 29) и `rejected` (3), и код его
не читал НИГДЕ — ни промпт, ни детерминированный слой.

Но `validated` жизненным циклом не является, и подменять одно другим
нельзя: это отметка внешней валидации на ОДНОМ документе кейсодателя
(n=12). Три типа с `rejected` дают настоящие находки на эталоне.
Поэтому `validated` остался наблюдением, а управление — новое поле
`status`, и здесь проверяется именно оно.

Главный тест — `test_status_field_does_not_change_the_prompt`: правка
не должна сдвинуть метрики, снятые на прежнем тексте таксономии.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import run_review                                              # noqa: E402
import docreview                                               # noqa: E402

CORE_DEFECTS = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "defects.yaml")
PACK_DEFECTS = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "review-packs", "mts-net", "0.2", "defects.yaml")

# Типы без наблюдений в эталоне: не «нулевая полнота», а отсутствие
# измерений — ровно то, что статус calibrating и должен обозначать.
EXPECTED_CALIBRATING = {"DANGLING_REFERENCE", "SCHEMA_INCONSISTENCY",
                        "TIMEZONE_INCONSISTENT", "VAGUE_WORDING"}


def _taxonomy(defects):
    fd, path = tempfile.mkstemp(suffix=".yaml")
    import yaml
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        yaml.safe_dump({"defects": defects}, fh, allow_unicode=True)
    return path


def _rule(rid, status=None, **kw):
    d = {"id": rid, "name": rid.lower(), "severity": "medium",
         "detectable_by": "llm", "description": "описание " + rid}
    if status is not None:
        d["status"] = status
    d.update(kw)
    return d


# --- 1. Правка не двигает метрики ----------------------------------------

# sha256 текста таксономии, уходящего в промпт, СНЯТЫЙ ДО добавления поля
# `status` (коммит f8c044e, `git stash` + пересчёт). Метрики 89% по месту /
# 78% по типу получены именно на этом тексте.
#
# Хеш, а не набор подстрок: первая версия теста проверяла количество правил
# и наличие четырёх идентификаторов, и была отклонена на ревью справедливо —
# перестановка правил, правка описания или пропажа другого содержимого
# оставались бы зелёными.
TAXONOMY_PROMPT_SHA256 = (
    "52cc890928e5756423c248ffe1c3acc2e4ea6cd2f111944871b0be35b72d8d59")


def test_status_field_does_not_change_the_prompt():
    """Текст таксономии для промпта не изменился НИ НА СИМВОЛ.

    Это главный тест правки. Известно, что смена файла таксономии сдвигает
    результат модели — доказано отдельным контрольным экспериментом
    (`data/ab_taxonomy`, шесть прогонов, диапазоны не пересекаются).
    Поэтому «поле добавили, промпт не тронули» нужно доказывать побитово,
    а не наличием подстрок.

    Красный тест здесь означает «промпт изменился, метрики надо переснимать»,
    а не «тест устарел».
    """
    import hashlib
    text, ids, defects = run_review.load_taxonomy(CORE_DEFECTS)
    actual = hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert actual == TAXONOMY_PROMPT_SHA256, (
        "текст таксономии для промпта изменился: %s вместо %s. "
        "Метрики сняты на прежнем тексте — либо откатить правку, "
        "либо переснять полноту и обновить хеш вместе с ней."
        % (actual, TAXONOMY_PROMPT_SHA256))
    assert len(defects) == 29 and len(ids) == 29
    # Типы calibrating остаются в промпте: они РАБОТАЮТ, просто не измерены.
    for rid in EXPECTED_CALIBRATING:
        assert rid in text, rid


def test_shipped_taxonomies_declare_status_for_every_type():
    """И ядро, и пакет объявляют статус у всех 29 типов."""
    import yaml
    for path in (CORE_DEFECTS, PACK_DEFECTS):
        data = yaml.safe_load(open(path, encoding="utf-8"))
        missing = [d["id"] for d in data["defects"] if "status" not in d]
        assert not missing, (path, missing)
        calibrating = {d["id"] for d in data["defects"]
                       if d["status"] == "calibrating"}
        assert calibrating == EXPECTED_CALIBRATING, (path, calibrating)


def test_conventions_and_retired_have_no_status():
    """Конвенции и снятые типы — не правила жизненного цикла.

    Конвенция это «не считать дефектом», retired уже снят и хранится
    как история; статус там был бы бессмысленным полем.
    """
    import yaml
    for path in (CORE_DEFECTS, PACK_DEFECTS):
        data = yaml.safe_load(open(path, encoding="utf-8"))
        for section in ("conventions", "retired_defects"):
            for item in data.get(section) or []:
                assert "status" not in item, (path, section, item.get("id"))


# --- 2. Статусы управляют применением ------------------------------------

def test_draft_and_deprecated_are_excluded_everywhere():
    """Выключенное правило не идёт ни в промпт, ни в список допустимых id.

    Оба места важны: `verify` отбрасывает находки с неизвестным id, и если
    правило убрать только из промпта, модель всё равно могла бы его вернуть.
    """
    path = _taxonomy([_rule("ALIVE", "active"),
                      _rule("WIP", "draft"),
                      _rule("OLD", "deprecated"),
                      _rule("TUNING", "calibrating")])
    try:
        text, ids, defects = run_review.load_taxonomy(path)
        assert ids == {"ALIVE", "TUNING"}, ids
        assert [d["id"] for d in defects] == ["ALIVE", "TUNING"]
        assert "WIP" not in text and "OLD" not in text
        assert "ALIVE" in text and "TUNING" in text
    finally:
        os.unlink(path)


def test_missing_status_defaults_to_active():
    """Таксономии, выпущенные до правки, работают как раньше."""
    path = _taxonomy([_rule("NO_STATUS_FIELD")])
    try:
        _, ids, _ = run_review.load_taxonomy(path)
        assert ids == {"NO_STATUS_FIELD"}
        assert run_review.rule_status({"id": "X"}) == "active"
    finally:
        os.unlink(path)


def test_unknown_status_is_an_error_not_silently_active():
    """Опечатка в статусе иначе молча включала бы правило."""
    path = _taxonomy([_rule("TYPO", "activ")])
    try:
        run_review.load_taxonomy(path)
    except run_review.TaxonomyInvalid as e:
        assert "TYPO" in str(e) and "activ" in str(e), str(e)
    else:
        raise AssertionError("неизвестный статус принят")
    finally:
        os.unlink(path)


def test_calibrating_rules_still_work():
    """calibrating — рабочее правило, а не выключенное.

    Разница с draft именно в этом: тип ищется и выдаётся, но помечен,
    потому что полнота и точность по нему не измерены.
    """
    path = _taxonomy([_rule("TUNING", "calibrating")])
    try:
        text, ids, defects = run_review.load_taxonomy(path)
        assert ids == {"TUNING"}
        assert "TUNING" in text
        assert len(defects) == 1
    finally:
        os.unlink(path)


# --- 3. Детерминированный слой подчиняется тем же статусам ---------------

def test_deterministic_findings_of_disabled_rules_are_dropped():
    """Иначе выключенное правило работало бы в одном из двух слоёв.

    Детерминированный слой идёт по template.yaml и о статусах не знает,
    поэтому отсев его находок — отдельный шаг. Половинчатое выключение
    и есть та болезнь, на которую указывал аудит.
    """
    statuses = {"ALIVE": "active", "WIP": "draft", "OLD": "deprecated",
                "TUNING": "calibrating"}
    findings = [{"defect_id": rid, "quote": "цитата " + rid}
                for rid in ("ALIVE", "WIP", "OLD", "TUNING", "NOT_IN_TAXONOMY")]
    kept, off = docreview._split_by_rule_status(findings, statuses)
    assert [f["defect_id"] for f in kept] == ["ALIVE", "TUNING", "NOT_IN_TAXONOMY"]
    assert [f["defect_id"] for f in off] == ["WIP", "OLD"]


def test_types_outside_taxonomy_are_kept():
    """Тип, определённый шаблоном, а не таксономией, гасить нельзя.

    Детерминированный слой выдаёт, например, TEMPLATE_SECTION_MISSING;
    молча выключить его из-за отсутствия в defects.yaml значило бы снять
    проверку, которую никто не выключал.
    """
    findings = [{"defect_id": "TEMPLATE_SECTION_MISSING", "quote": "q"}]
    kept, off = docreview._split_by_rule_status(findings, {"OTHER": "draft"})
    assert kept == findings and off == []


def test_duplicate_findings_survive_the_split():
    """Одинаковые по значению находки не теряются при отсеве.

    Первая версия этого теста называлась «не путаются» и обосновывала
    отсев по `id()` защитой от того, что `f not in off` выбросил бы обе.
    Проверка подсадкой это опровергла: обе реализации проходят тест
    одинаково, потому что равные находки несут один `defect_id` и потому
    один статус. Тест оставлен как проверка самого отсева, а ложное
    обоснование убрано и из кода.
    """
    a = {"defect_id": "ALIVE", "quote": "одинаково"}
    b = {"defect_id": "ALIVE", "quote": "одинаково"}
    c = {"defect_id": "WIP", "quote": "выключено"}
    kept, off = docreview._split_by_rule_status([a, b, c], {"ALIVE": "active",
                                                            "WIP": "draft"})
    assert len(kept) == 2 and len(off) == 1
    assert all(f["defect_id"] == "ALIVE" for f in kept)


# --- 4. Статус доходит до выдачи ----------------------------------------

def test_calibrating_is_visible_in_the_result():
    """Человек должен знать, что тип не откалиброван."""
    findings = [{"quote": "Срок хранения не определён.", "defect_id": "TUNING",
                 "severity": "medium", "explanation": "e", "suggestion": "s"},
                {"quote": "Загрузка выполняется ежедневно.", "defect_id": "ALIVE",
                 "severity": "medium", "explanation": "e", "suggestion": "s"}]
    result = docreview.build_review_result(
        "Срок хранения не определён.\nЗагрузка выполняется ежедневно.",
        "d.txt", "T", [], findings, "r-1", ("mts-net", "0.2"), "m",
        {"fragment": "dict2"}, 1.0,
        rule_statuses={"TUNING": "calibrating", "ALIVE": "active"})
    by_id = {f["defect_id"]: f for f in result["findings"]}
    assert by_id["TUNING"]["rule_status"] == "calibrating"
    # У active поля нет вовсе: иначе оно было бы шумом на каждом замечании.
    assert "rule_status" not in by_id["ALIVE"]


def test_result_with_rule_status_passes_the_contract():
    from contracts.validate_contract import validate_review_result
    findings = [{"quote": "Срок хранения не определён.", "defect_id": "TUNING",
                 "severity": "medium", "explanation": "e", "suggestion": "s"}]
    result = docreview.build_review_result(
        "Срок хранения не определён.", "d.txt", "T", [], findings, "run-1",
        ("mts-net", "0.2"), "qwen3:30b-a3b",
        {"fragment": "dict2", "global": "global"}, 12.0,
        document_sha256="a" * 64, rule_statuses={"TUNING": "calibrating"})
    validate_review_result(result)


# --- 5. validated остаётся наблюдением, а не управлением ----------------

def test_validated_does_not_disable_rules():
    """`validated: rejected` НЕ выключает правило.

    Это отметка внешней валидации на одном документе (n=12), и три типа
    с этой отметкой дают настоящие находки на эталоне. Выключать по ней —
    значит терять полноту из-за наблюдения на двенадцати замечаниях.
    Решение об отключении принимает человек, меняя `status`.
    """
    import yaml
    data = yaml.safe_load(open(CORE_DEFECTS, encoding="utf-8"))
    rejected = [d for d in data["defects"] if d.get("validated") == "rejected"]
    assert rejected, "в таксономии должны остаться отметки rejected"
    _, ids, _ = run_review.load_taxonomy(CORE_DEFECTS)
    for d in rejected:
        assert d["id"] in ids, d["id"]


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    for t in TESTS:
        t()
        print("ok  %s" % t.__name__)
    print("\n%d passed" % len(TESTS))
