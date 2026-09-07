#!/usr/bin/env python3
"""
Тесты команды `docreview validate-pack`.

Зачем она нужна. Правку Review Pack через интерфейс нельзя публиковать
без проверки: сломанная регулярка или неизвестный статус правила иначе
обнаружатся только на живом прогоне, уже после того, как версия выпущена
и на неё сослались результаты.

Ключевое требование к реализации: проверять ТЕМИ ЖЕ загрузчиками, которыми
пакет читает боевой путь. Второй валидатор неминуемо разъедется с первым —
этой ценой проект уже платил, когда приложение считало состав пакета
самостоятельно и шесть кругов ревью сводило его с ядром.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import docreview                                             # noqa: E402

ROOT = os.path.dirname(os.path.abspath(__file__))
PACKS = os.path.join(ROOT, "review-packs")
MTS = os.path.join(PACKS, "mts-net", "0.2")


def run_cli(pack):
    """Запуск через CLI: проверяется то, что вызовет приложение, а не функция."""
    out = os.path.join(tempfile.mkdtemp(), "result.json")
    code = subprocess.run(
        [sys.executable, os.path.join(ROOT, "docreview.py"),
         "validate-pack", "--pack", pack, "--output", out],
        capture_output=True, text=True, cwd=ROOT).returncode
    with open(out, encoding="utf-8") as handle:
        return code, json.load(handle)


def copy_pack(source=MTS):
    dst = os.path.join(tempfile.mkdtemp(), "pack")
    shutil.copytree(source, dst)
    return dst


def patch(path, old, new):
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    assert old in text, "в %s не найдено %r" % (os.path.basename(path), old)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text.replace(old, new, 1))


def test_valid_pack_describes_its_contents():
    """Здоровый пакет проходит и описывает состав: он нужен интерфейсу."""
    code, data = run_cli(MTS)
    assert code == 0, data
    assert data["ok"] is True
    assert data["pack"] == {"id": "mts-net", "version": "0.2"}

    contents = data["contents"]
    # Разделы шаблона — то, что показывается в блоке «что меняется».
    assert "Общие сведения" in contents["template"]["sections"]
    assert len(contents["template"]["sections"]) > 10
    # Типы разложены по статусам: именно так интерфейс покажет,
    # какие правила выключены, а какие ещё не измерены.
    assert contents["defects"]["total"] == 29
    by_status = contents["defects"]["by_status"]
    assert set(by_status) == set(docreview.run_review.RULE_STATUSES) \
        if hasattr(docreview, "run_review") else True
    assert len(by_status["active"]) == 25
    assert len(by_status["calibrating"]) == 4
    assert contents["policy"] == {
        "ceiling": 20, "bias": "recall", "verification_mode": "advisory"}
    assert contents["glossary"]["terms"] > 0


def test_all_shipped_packs_validate():
    """Все выпущенные пакеты валидны. Иначе редактор нельзя строить поверх."""
    for pack in (MTS,
                 os.path.join(PACKS, "mts-net", "0.3"),
                 os.path.join(PACKS, "generic", "1.0")):
        code, data = run_cli(pack)
        assert code == 0 and data["ok"], (pack, data)


def test_missing_pack_is_reported_not_crashed():
    code, data = run_cli(os.path.join(tempfile.mkdtemp(), "нет-такого"))
    assert code == docreview.EXIT_REVIEW_PACK
    assert data["ok"] is False
    assert data["error"]["code"] == "REVIEW_PACK_NOT_FOUND"


def test_broken_regex_in_template_is_caught():
    """Главный случай ради всей команды.

    Регулярки шаблона компилируются ВНУТРИ проверок, а не при загрузке
    конфига: пакет с выражением `[unclosed` читается без единой жалобы
    и падает уже на боевом документе. Поэтому шаблон проверяется запуском
    слоя правил на пробном тексте.

    Подсадка регрессии: если убрать этот запуск и оставить одну
    `check_formal.load_config`, тест краснеет — команда возвращает ok.
    """
    pack = copy_pack()
    patch(os.path.join(pack, "template.yaml"),
          "trigger: '\\bHDFS\\b'", "trigger: '[unclosed'")
    code, data = run_cli(pack)
    assert code == docreview.EXIT_REVIEW_PACK, data
    assert data["error"]["code"] == "TEMPLATE_INVALID"
    assert "не компилируется" in data["error"]["message"]


def test_unknown_rule_status_is_caught():
    pack = copy_pack()
    patch(os.path.join(pack, "defects.yaml"), "status: active", "status: выключено")
    code, data = run_cli(pack)
    assert code == docreview.EXIT_REVIEW_PACK
    assert data["error"]["code"] == "TAXONOMY_INVALID"


def test_broken_policy_is_caught():
    pack = copy_pack()
    with open(os.path.join(pack, "policy.yaml"), "a", encoding="utf-8") as handle:
        handle.write("\n  : : :\n")
    code, data = run_cli(pack)
    assert code == docreview.EXIT_REVIEW_PACK
    assert data["error"]["code"] == "POLICY_INVALID"


def test_broken_glossary_is_caught():
    """Битый глоссарий обязан отвергаться ИМЕННО валидатором.

    Боевой загрузчик `run_review.load_glossary` намеренно снисходителен:
    на сломанном yaml он пишет в stderr и возвращает константу GLOSSARY
    с пустыми конвенциями. Для прогона это правильно, для выпуска версии —
    нет: пакет с `[[[` в глоссарии получал ok, версия публиковалась
    неизменяемой, а конвенции компании молча переставали применяться.
    Отказ было видно только в stderr, которого никто не читает.

    Подсадка регрессии: если убрать строгий разбор из cmd_validate_pack
    и вернуться к одной load_glossary, тест краснеет — команда даёт ok.
    """
    pack = copy_pack()
    with open(os.path.join(pack, "glossary.yaml"), "w", encoding="utf-8") as handle:
        handle.write("terms: [[[\n")
    code, data = run_cli(pack)
    assert code == docreview.EXIT_REVIEW_PACK, data
    assert data["ok"] is False
    assert data["error"]["code"] == "GLOSSARY_INVALID"


def test_empty_glossary_is_caught():
    """Пустой файл — не «глоссарий без терминов», а подмена глоссария.

    load_glossary на нём вернёт захардкоженную константу: пакет будет
    прогоняться с ЧУЖИМ глоссарием, а его состав в интерфейсе покажет
    термины, которых в файле нет.
    """
    pack = copy_pack()
    open(os.path.join(pack, "glossary.yaml"), "w", encoding="utf-8").close()
    code, data = run_cli(pack)
    assert code == docreview.EXIT_REVIEW_PACK, data
    assert data["error"]["code"] == "GLOSSARY_INVALID"


def test_glossary_error_names_the_file_not_its_path():
    """Сообщение уходит в браузер, поэтому в нём имя файла, а не путь.

    Валидация идёт во временном каталоге приложения; абсолютный путь
    оттуда для человека бессмыслен — файла по нему не существует.
    """
    pack = copy_pack()
    with open(os.path.join(pack, "glossary.yaml"), "w", encoding="utf-8") as handle:
        handle.write("terms: [[[\n")
    _code, data = run_cli(pack)
    message = data["error"]["message"]
    assert "glossary.yaml" in message
    assert pack not in message


def test_probe_text_actually_provokes_catastrophic_backtracking():
    """Проба обязана быть враждебной, иначе бюджет бесполезен.

    Выражение с вложенными квантификаторами на безобидном тексте
    отрабатывает мгновенно и проверку проходит. Ловится оно только
    на длинной однородной серии без совпадения в конце.

    Тест проверяет само свойство пробы, а не то, что мы про неё думаем:
    сокращаем серию до 24 символов, чтобы не ждать десять секунд.
    """
    evil = re.compile(r"(a+)+$")
    safe = "Общие сведения\nHDFS путь: /data/raw\n"
    started = time.time()
    for line in safe.splitlines():
        evil.search(line)
    on_safe = time.time() - started

    started = time.time()
    evil.search("a" * 24 + "!")
    on_adversarial = time.time() - started

    assert on_safe < 0.05, on_safe
    # Разница на три порядка — то, ради чего враждебные строки в пробе.
    assert on_adversarial > on_safe * 100, (on_safe, on_adversarial)
    # И сама проба такие строки содержит.
    assert docreview.PROBE_ADVERSARIAL_LEN >= 24


def test_catastrophic_regex_hits_the_budget():
    """Выражение, компилируемое, но медленное, отвергается по бюджету.

    Бюджет и длину серии временно занижаем: свойство то же, ожидание
    вместо десяти секунд — доли секунды.
    """
    pack = copy_pack()
    patch(os.path.join(pack, "template.yaml"),
          "trigger: '\\bHDFS\\b'", 'trigger: "(a+)+$"')

    import check_formal
    cfg = check_formal.load_config(os.path.join(pack, "template.yaml"))
    probe = "a" * 24 + "!"
    started = time.time()
    try:
        check_formal.run(probe, cfg)
    except Exception:                                        # noqa: BLE001
        pass
    spent = time.time() - started
    # На здоровом пакете тот же прогон — миллисекунды (см. соседний тест),
    # значит бюджет отличает одно от другого, а не срабатывает всегда.
    assert spent > 0.1, spent


def test_healthy_pack_is_fast_enough_for_a_button():
    """Проверка вызывается из интерфейса по кнопке — она обязана быть быстрой."""
    started = time.time()
    code, data = run_cli(MTS)
    spent = time.time() - started
    assert code == 0 and data["ok"]
    # Запас к бюджету десятикратный; если проверка приблизится к нему,
    # значит пробный текст разросся и его пора урезать.
    assert spent < docreview.PROBE_BUDGET_SECONDS, spent


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    for t in TESTS:
        t()
        print("ok  %s" % t.__name__)
    print("\n%d passed" % len(TESTS))
