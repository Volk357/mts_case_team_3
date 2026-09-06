#!/usr/bin/env python3
"""
Тесты второго Review Pack — доказательство платформенности.

Главное продуктовое утверждение проекта: «под другую организацию инструмент
настраивается конфигурацией, а не кодом». До 6 сентября оно держалось на
архитектуре (приложение не знает про промпты и таксономию), но проверить его
было нечем: пакет существовал ровно один.

Здесь проверяется второй профиль — универсальная техническая спецификация
сервиса вместо описания витрины данных. У него другая структура разделов,
другой глоссарий, другие описания типов и **противоположная политика
приёмки**: у МТС NET склонность к полноте и потолок 20, здесь склонность
к точности, потолок 12 и верификация в режиме отсечения.

Модель здесь не вызывается: проверяется, что конфигурация загружается,
детерминированный слой работает на документе другого типа и политика
доезжает до результата.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import check_formal                                            # noqa: E402
import docreview                                               # noqa: E402
import run_review                                              # noqa: E402

ROOT = os.path.dirname(os.path.abspath(__file__))
GENERIC = os.path.join(ROOT, "review-packs", "generic", "1.0")
MTS = os.path.join(ROOT, "review-packs", "mts-net", "0.2")
DOC = os.path.join(ROOT, "data", "generic", "service_spec.txt")


def test_generic_pack_resolves_with_all_four_files():
    """Пакет собран полностью: манифест объявляет четыре файла, все на месте."""
    pack_id, version, tpl, dfx, glo, pol, warnings = docreview.resolve_pack(GENERIC)
    assert (pack_id, version) == ("generic", "1.0")
    assert warnings == [], warnings
    for path, name in ((tpl, "template.yaml"), (dfx, "defects.yaml"),
                       (glo, "glossary.yaml"), (pol, "policy.yaml")):
        assert path and os.path.isfile(path), name


def test_generic_policy_is_the_opposite_of_mts():
    """Политика второго профиля противоположна первому.

    Это и есть предмет доказательства: одно ядро, один код, но заказчик
    выбирает другое поведение — потолок, склонность и режим верификации.
    Если бы политики совпадали, пакет ничего бы не показывал.
    """
    generic = run_review.load_policy(os.path.join(GENERIC, "policy.yaml"))
    mts = run_review.load_policy(os.path.join(MTS, "policy.yaml"))

    assert generic["ceiling"] == 12 and mts["ceiling"] == 20
    assert generic["bias"] == "precision" and mts["bias"] == "recall"
    assert generic["verification"]["mode"] == "enforcing"
    assert mts["verification"]["mode"] == "advisory"
    # Тексты для промпта тоже разные — иначе склонность была бы объявлена,
    # но не применена.
    assert generic["prompt"]["bias"] != mts["prompt"]["bias"]
    assert "не выдавай" in generic["prompt"]["bias"]
    assert "выдавай" in mts["prompt"]["bias"]


def test_generic_taxonomy_loads_and_is_smaller():
    """Таксономия профиля своя: меньше типов, все помечены как неизмеренные."""
    import yaml
    text, ids, defects = run_review.load_taxonomy(os.path.join(GENERIC, "defects.yaml"))
    assert len(defects) >= 20, len(defects)
    # Тип, привязанный к предметной области витрин, в этот профиль не взят.
    assert "HDFS_PATH_INCOMPLETE" not in ids

    data = yaml.safe_load(open(os.path.join(GENERIC, "defects.yaml"), encoding="utf-8"))
    statuses = {d["status"] for d in data["defects"]}
    # Наблюдений по этому профилю нет ни по одному типу — честный статус.
    assert statuses == {"calibrating"}, statuses


def test_generic_sections_differ_from_mts():
    """Структура документа другая — это другой класс документов."""
    generic = check_formal.load_config(os.path.join(GENERIC, "template.yaml"))
    mts = check_formal.load_config(os.path.join(MTS, "template.yaml"))
    g_names = {s["name"] for s in generic["sections"]}
    m_names = {s["name"] for s in mts["sections"]}
    assert "Внешние интерфейсы" in g_names
    assert "Критерии приёмки" in g_names
    # Пересечение допустимо (НФТ есть у обоих), но наборы не совпадают.
    assert g_names != m_names
    assert len(g_names - m_names) >= 5, g_names - m_names


def test_rule_layer_finds_defects_in_service_spec():
    """Детерминированный слой работает на документе другого типа.

    Ключевая проверка платформенности: код проверок не менялся, поменялась
    только конфигурация — и слой нашёл заложенные в документ дефекты.
    """
    cfg = check_formal.load_config(os.path.join(GENERIC, "template.yaml"))
    text = open(DOC, encoding="utf-8").read()
    result = check_formal.run(text, cfg)
    ids = [f["defect_id"] for f in result["findings"]]

    assert "PLACEHOLDER_LEFT" in ids, ids      # TBD и «уточняется на этапе»
    assert "VAGUE_WORDING" in ids, ids         # «по возможности», «и т.д.»
    # Проверка путей HDFS в этом профиле не срабатывает: таких документов нет.
    assert "HDFS_PATH_INCOMPLETE" not in ids, ids
    # Цитаты — настоящие куски документа.
    for f in result["findings"]:
        assert f["quote"].strip() in text, f["quote"]


def test_generic_policy_reaches_the_result():
    """Политика второго пакета видна в выдаче, а не только в файле."""
    policy = run_review.load_policy(os.path.join(GENERIC, "policy.yaml"))
    text = open(DOC, encoding="utf-8").read()
    cfg = check_formal.load_config(os.path.join(GENERIC, "template.yaml"))
    result = docreview.build_review_result(
        text, "service_spec.txt", "Спецификация сервиса", [], [],
        "r-1", ("generic", "1.0"), "m", {"fragment": "dict2"}, 1.0,
        cfg=cfg, policy=policy)
    assert result["review_pack"] == {
        "id": "generic", "version": "1.0",
        "policy": {"ceiling": 12, "bias": "precision"},
    }


def test_both_packs_pass_the_contract():
    """Результат по обоим профилям валиден по одной и той же схеме.

    Единый контракт — вторая половина утверждения о платформенности:
    приложение не знает, какой профиль применён.
    """
    from contracts.validate_contract import validate_review_result
    text = open(DOC, encoding="utf-8").read()
    # Версия берётся из МАНИФЕСТА каждого пакета, а не пишется руками:
    # приложение сверяет id и version результата с заданием и бракует
    # результат при расхождении. Захардкоженная «1.0» для mts-net (там 0.2)
    # давала бы результат, который приложение отвергнет, — тест проходил бы,
    # ничего не доказывая. Найдено на ревью.
    for pack_dir in (GENERIC, MTS):
        pack_id, version, *_ = docreview.resolve_pack(pack_dir)
        cfg = check_formal.load_config(os.path.join(pack_dir, "template.yaml"))
        policy = run_review.load_policy(os.path.join(pack_dir, "policy.yaml"))
        result = docreview.build_review_result(
            text, "d.txt", "T", check_formal.run(text, cfg)["findings"], [],
            "run-1", (pack_id, version), "qwen3:30b-a3b",
            {"fragment": "dict2", "global": "global"}, 12.0,
            document_sha256="a" * 64, cfg=cfg, policy=policy)
        validate_review_result(result)
        assert result["review_pack"]["version"] == version
    # Версии действительно разные — иначе сверка ничего не проверяет.
    assert docreview.resolve_pack(GENERIC)[1] != docreview.resolve_pack(MTS)[1]




def test_hdfs_check_never_fires_in_generic_profile():
    """Проверка путей HDFS выключена заведомо несовпадающим триггером.

    Блокер ревью: с триггером `\\bHDFS\\b` любое упоминание слова запускало
    проверку и выдавало тип HDFS_PATH_INCOMPLETE, которого в таксономии
    этого профиля нет. Типы вне таксономии считаются применяемыми
    (иначе выключились бы проверки, определённые шаблоном), поэтому
    замечание дошло бы до пользователя.
    """
    cfg = check_formal.load_config(os.path.join(GENERIC, "template.yaml"))
    text = (open(DOC, encoding="utf-8").read()
            + "\nВыгрузка в HDFS не поддерживается.\n"
            + "\nHDFS путь: /data/raw\n")
    ids = [f["defect_id"] for f in check_formal.run(text, cfg)["findings"]]
    assert "HDFS_PATH_INCOMPLETE" not in ids, ids
    # При этом остальные проверки профиля работают.
    assert "PLACEHOLDER_LEFT" in ids, ids


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    for t in TESTS:
        t()
        print("ok  %s" % t.__name__)
    print("\n%d passed" % len(TESTS))
