#!/usr/bin/env python3
"""
Тесты политики приёмки замечаний (acceptance policy).

Что здесь доказывается и почему именно так.

Правка выносила три решения — квоту на фрагмент, квоту на документ и
формулировку склонности «сомневаешься — выдавай» — из текста промпта
и из Python-констант в версионируемый policy.yaml пакета. Такая правка
опасна ровно одним: она может незаметно изменить промпт, а метрики
(полнота 88% по месту / 77% по типу) сняты на прежнем тексте. Поэтому
первые два теста — снимки собранного промпта побуквенно, а не проверки
наличия подстрок. Проверка «в промпте есть слово квота» прошла бы и на
изменившемся тексте, и именно такие проверки уже подводили в этом
проекте (см. parity-method-assessment: contract-check ищут подстроки).

Остальные тесты — про то, что политика не может тихо разъехаться
с контрактом приложения (findings.maxItems = 20) и что сломанный
policy.yaml — это ошибка пакета, а не молчаливый откат на умолчания.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import run_review                                              # noqa: E402
import docreview                                               # noqa: E402

PACK = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    "review-packs", "mts-net", "0.2")


def _write_policy(text):
    fd, path = tempfile.mkstemp(suffix=".yaml")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


FULL_POLICY_YAML = """\
ceiling: %s
bias: %s
prompt:
  bias: '%s'
  fragment_quota: '%s'
  document_quota: '%s'
verification:
  mode: advisory
  batch_size: 8
"""


def _full_policy(ceiling=20, bias="recall", bias_text="Сомневаешься — выдавай.",
                 fragment_quota="От пяти до десяти на фрагмент.",
                 document_quota="От двух до шести на документ."):
    """Полный policy.yaml. Частичный ядром не принимается — см. load_policy."""
    return _write_policy(FULL_POLICY_YAML % (ceiling, bias, bias_text,
                                             fragment_quota, document_quota))


def _assert_same_text(actual, expected, label):
    """Сравнение целиком с показом ПЕРВОГО расхождения.

    Голый assert на многострочном тексте печатает две простыни, в которых
    расхождение в одном пробеле не найти глазами.
    """
    if actual == expected:
        return
    for i, (a, b) in enumerate(zip(actual, expected)):
        if a != b:
            raise AssertionError(
                "%s разошёлся на символе %d\n  ожидалось: ...%r\n  получено:  ...%r"
                % (label, i, expected[max(0, i - 60):i + 60],
                   actual[max(0, i - 60):i + 60]))
    raise AssertionError(
        "%s: длины разные (%d против %d), хвост %r"
        % (label, len(actual), len(expected),
           (actual if len(actual) > len(expected) else expected)[
               min(len(actual), len(expected)):][:160]))


# --- 1. Перенос формата не изменил промпт ---------------------------------
#
# Снимки промпта ЦЕЛИКОМ. Первая версия этих тестов проверяла наличие двух
# подстрок и была отклонена на ревью справедливо: добавление, удаление или
# правка любой другой строки промпта оставались бы зелёными, а метрики
# (88% по месту / 77% по типу) сняты на промпте целиком, не на двух его
# строках. Это тот же неработающий метод, что и *_contract_check.py:
# поиск подстроки вместо проверки поведения.
#
# Если промпт меняется намеренно — снимок правится вместе с ним, И метрики
# переснимаются. Красный тест здесь означает «промпт изменился», а не
# «тест устарел».

EXPECTED_DICT2 = """Ты ревьюишь техническое задание на разработку витрины или потока данных в телеком-компании.

Проверь фрагмент на наличие дефектов из списка ниже.

СПИСОК ТИПОВ ДЕФЕКТОВ:
<TAXONOMY>

ОБЪЕКТЫ, ОПРЕДЕЛЁННЫЕ В ЭТОМ ДОКУМЕНТЕ:
<KNOWN>

Ты видишь только один фрагмент, но документ больше. Перечисленные выше объекты в документе упомянуты — возможно, в другом разделе, которого ты сейчас не видишь.

Что из этого следует и что НЕ следует:
- НЕ выдавай для объектов из списка замечаний о том, что объект не описан, не определён, отсутствует раздел с его структурой или перечнем полей. Их структура может быть описана в невидимом тебе разделе.
- Это единственное ограничение. Всё остальное про эти объекты проверяй как обычно: не указано расположение кластера или схемы, осталась заглушка вместо значения, не задан ключ, не описан граничный случай, противоречие с другим утверждением фрагмента — всё это дефекты, и наличие имени в списке ничего не отменяет.
- Если фрагмент ссылается на объект, которого в списке НЕТ, — это дефект.

ОБЩЕИЗВЕСТНЫЕ ТЕРМИНЫ (расшифровывать в документе не требуется):
<GLOSSARY>

НЕ проси объяснить эти термины и не спорь с их значением. Аналитики и разработчики знают их без пояснений.

СОГЛАШЕНИЯ КОМПАНИИ (не считать дефектами):
<CONVENTIONS>

КАК РАБОТАТЬ:
Пройди по списку типов дефектов сверху вниз и по каждому спроси себя: есть ли во фрагменте место, подпадающее под этот тип? Проверь весь список до конца, не останавливайся на первых находках.

Если одно место подпадает сразу под несколько типов — выдай замечание по каждому типу отдельно, не выбирай главный. Если под один тип подпадают несколько разных мест — выдай замечание по каждому месту.

ПРАВИЛА:
1. quote — дословная копия из фрагмента, символ в символ.
2. Цитируй содержательную строку, а не заголовок таблицы, не название раздела и не одно имя поля. Цитата должна показывать проблему, а не указывать на неё пальцем.
3. defect_id — строго один из id списка типов. Свои идентификаторы не придумывай.
4. Полнота важнее осторожности. Пропущенная проблема хуже лишней придирки. Сомневаешься — выдавай.
5. В suggestion не упоминай таблицы, поля, схемы и значения, которых нет в документе. Не выдумывай примеры вида CLUSTER_PROD, SCHEMA_CDM_NETS_PROD, region_id, UTC+3. Если конкретное значение неизвестно — так и напиши: указать конкретное значение.
6. Ориентир: от пяти до десяти замечаний на фрагмент. Меньше пяти — скорее всего ты не дошёл до конца списка типов.
7. explanation — почему разработчик придёт с вопросом именно по этому месту.

Верни только массив json, без пояснений.

ФРАГМЕНТ ТЕХНИЧЕСКОГО ЗАДАНИЯ:
<FRAGMENT>"""


EXPECTED_GLOBAL = """Ты ревьюишь техническое задание на разработку витрины или потока данных в телеком-компании.

Перед тобой ДОКУМЕНТ ЦЕЛИКОМ. Твоя задача — найти дефекты, которые видны только при взгляде на весь документ сразу: когда одно утверждение противоречит другому, когда объект упомянут, но нигде не описан, когда одно и то же названо по-разному в разных разделах.

ИЩИ ТОЛЬКО ЭТИ ТИПЫ ДЕФЕКТОВ:
<TAXONOMY>

НА ЧТО СМОТРЕТЬ В ПЕРВУЮ ОЧЕРЕДЬ:
1. Сопоставь раздел бизнес-требований с разделом требований к результату. Способ загрузки, регламент, правила обновления, глубина данных — не противоречат ли утверждения друг другу?
2. Собери все имена таблиц и полей, которые встречаются в алгоритме расчёта. Для каждого проверь: описана ли его структура где-нибудь в документе? Если объект используется, но нигде не описан — это дефект.
3. Сравни объявленные метрики и нефункциональные требования между собой.
4. Проверь, для всех ли перечисленных объектов заданы сроки хранения, регламент и объём.
5. Проверь, не названы ли одни и те же сущности по-разному в разных разделах и не описаны ли схожим образом два разных поля.

ОБЩЕИЗВЕСТНЫЕ ТЕРМИНЫ (расшифровывать не требуется):
<GLOSSARY>

ПРАВИЛА:
1. quote — дословная копия из документа, символ в символ. Для противоречия цитируй ОДНО из конфликтующих утверждений, а второе назови в explanation.
2. defect_id — строго один из списка выше.
3. explanation обязан называть обе стороны проблемы: что и чему противоречит, какой объект и где используется без описания.
4. Не выдумывай объекты, которых нет в документе.
5. Не дублируй: одна проблема — одно замечание.
6. Ориентир: от двух до шести замечаний на документ. Это дополнительный проход, основные дефекты уже найдены отдельно.

Верни только массив json, без пояснений.

ДОКУМЕНТ ЦЕЛИКОМ:
<DOCUMENT>"""


def test_fragment_prompt_is_byte_identical_to_measured_text():
    """Промпт фрагментов с политикой пакета — тот же, на котором сняты метрики."""
    policy = run_review.load_policy(os.path.join(PACK, "policy.yaml"))
    prompt = run_review.PROMPT_DICT2.format(
        taxonomy="<TAXONOMY>", fragment="<FRAGMENT>", known_objects="<KNOWN>",
        glossary="<GLOSSARY>", conventions="<CONVENTIONS>",
        policy_bias=policy["prompt"]["bias"],
        policy_quota=policy["prompt"]["fragment_quota"])
    _assert_same_text(prompt, EXPECTED_DICT2, "PROMPT_DICT2")


def test_global_prompt_is_byte_identical_to_measured_text():
    policy = run_review.load_policy(os.path.join(PACK, "policy.yaml"))
    prompt = run_review.PROMPT_GLOBAL.format(
        taxonomy="<TAXONOMY>", glossary="<GLOSSARY>", document="<DOCUMENT>",
        policy_quota=policy["prompt"]["document_quota"])
    _assert_same_text(prompt, EXPECTED_GLOBAL, "PROMPT_GLOBAL")


def test_frozen_prompts_have_no_policy_placeholders():
    """Заморожённые режимы политикой не параметризованы — они точка сравнения.

    Если в baseline/taxonomy/dict появится {policy_*}, их вызовы в `run`
    упадут по KeyError на боевом пути, а прогоны прошлых замеров перестанут
    воспроизводиться.
    """
    for mode in ("baseline", "taxonomy", "dict"):
        tpl = run_review.PROMPTS[mode]
        assert "{policy_" not in tpl, mode


def test_pack_policy_equals_default_policy():
    """Пакет 0.2 несёт ровно ту политику, что была зашита в коде.

    Это тест не на «политику вообще», а на конкретную версию пакета:
    метрики сняты на 0.2, и выкатка не должна их сдвинуть. Новая версия
    пакета вправе нести другую политику — тогда меняется и версия.
    """
    assert run_review.load_policy(os.path.join(PACK, "policy.yaml")) == \
        run_review.DEFAULT_POLICY


def test_missing_policy_file_falls_back_to_default():
    """Пакет без policy.yaml (выпущенный до правки) работает как раньше."""
    assert run_review.load_policy(None) == run_review.DEFAULT_POLICY


def test_default_policy_is_not_shared_between_calls():
    """Загрузчик отдаёт копию: правка результата не портит умолчания.

    Без deepcopy один вызов, поменявший ceiling у себя, менял бы его
    для всего процесса — включая следующий документ в очереди воркера.
    """
    first = run_review.load_policy(None)
    first["ceiling"] = 1
    first["prompt"]["bias"] = "испорчено"
    assert run_review.load_policy(None)["ceiling"] == 20
    assert run_review.DEFAULT_POLICY["prompt"]["bias"].startswith("Полнота важнее")


# --- 2. Политика не может разъехаться с контрактом ------------------------

def test_ceiling_above_contract_is_rejected():
    """Потолок выше findings.maxItems = 20 — ошибка пакета, не обрезание.

    Молча обрезав, мы получили бы пакет, который объявляет одно, а делает
    другое; отдав как есть — результат, который приложение бракует целиком
    с невнятной причиной.
    """
    path = _full_policy(ceiling=25)
    try:
        run_review.load_policy(path)
    except run_review.PolicyInvalid as e:
        assert "25" in str(e) and "20" in str(e), str(e)
    else:
        raise AssertionError("потолок 25 принят, хотя контракт разрешает 20")
    finally:
        os.unlink(path)


def test_ceiling_below_contract_is_allowed_and_applied():
    """Опустить потолок политикой можно — и он реально режет выдачу."""
    path = _full_policy(ceiling=3)
    try:
        policy = run_review.load_policy(path)
        assert policy["ceiling"] == 3
        findings = [{"quote": "q%d" % i, "defect_id": "X", "severity": "medium",
                     "explanation": "e", "suggestion": "s"} for i in range(10)]
        result = docreview.build_review_result(
            "q0\nq1\nq2\nq3\nq4\nq5\nq6\nq7\nq8\nq9", "d.txt", "T",
            [], findings, "r-1", ("mts-net", "0.2"), "m",
            {"fragment": "dict2"}, 1.0, policy=policy)
        assert len(result["findings"]) == 3, len(result["findings"])
        assert result["review_pack"]["policy"]["ceiling"] == 3
    finally:
        os.unlink(path)


def test_run_full_applies_policy_ceiling_not_the_constant():
    """Потолок политики доходит до apply_budget внутри run_full.

    Тест понадобился после проверки на подсадку: заменив в run_full
    `apply_budget(kept, ceiling=policy["ceiling"])` обратно на
    `apply_budget(kept)`, все остальные тесты остались зелёными — потолок
    в боевом проходе не был покрыт ничем. Модель здесь не вызывается:
    подменяются оба прохода, проверяется только отсечение.
    """
    # Цитаты намеренно НЕ похожи друг на друга: dedupe склеивает близкие,
    # и на шаблонных «строка 1..9» до бюджета доезжала одна находка.
    quotes = [
        "Загрузка выполняется ежедневно в 03:00 по местному времени",
        "Глубина хранения витрины определяется отдельным регламентом",
        "Ключ соединения с таблицей источника выбирает разработчик",
        "Формат выгрузки согласуется на этапе приёмки",
        "Объём данных ориентировочно составляет несколько терабайт",
        "Фильтрация нерелевантных абонентов описана в приложении",
        "Расчёт агрегата ведётся по бизнес-правилам подразделения",
        "Права доступа выдаются по заявке владельца продукта",
        "Мониторинг качества настраивается после ввода в эксплуатацию",
    ]
    # defect_id тоже разные: dedupe группирует по типу и склеивает всё,
    # что ближе 500 символов, — на одном типе девять находок стали одной.
    findings = [{"quote": q, "defect_id": "TYPE_%d" % i, "severity": "medium",
                 "explanation": "e", "suggestion": "s"}
                for i, q in enumerate(quotes)]
    stub = {"findings": findings, "fragments": 1, "total_seconds": 0.0,
            "found_raw": 9, "verified": 9, "rejected_count": 0,
            "reject_reasons": {}, "rejected": [], "truncated_chars": 0}
    empty = dict(stub, findings=[], found_raw=0, verified=0)

    original_run, original_global = run_review.run, run_review.run_global
    run_review.run = lambda *a, **k: dict(stub)
    run_review.run_global = lambda *a, **k: dict(empty)
    try:
        doc = "\n".join(quotes)
        # verification off: тест про потолок, а слой semantic verdict
        # по умолчанию (advisory) пошёл бы в сеть.
        policy = dict(run_review.DEFAULT_POLICY, ceiling=4,
                      verification={"mode": "off", "batch_size": 8})
        result = run_review.run_full(doc, [], "<T>", set(), "<K>",
                                     frag_mode="dict2", policy=policy)
        assert len(result["findings"]) == 4, len(result["findings"])
        assert result["capped_away"] == 5, result["capped_away"]
    finally:
        run_review.run, run_review.run_global = original_run, original_global


def test_applied_policy_reaches_the_result():
    """Политика видна в выдаче: иначе «версионируемая» недоказуема."""
    result = docreview.build_review_result(
        "текст", "d.txt", "T", [], [], "r-1", ("mts-net", "0.2"), "m",
        {"fragment": "dict2"}, 1.0)
    assert result["review_pack"]["policy"] == {"ceiling": 20, "bias": "recall"}
    # Обязательные поля контракта на месте — политика их не вытеснила.
    assert result["review_pack"]["id"] == "mts-net"
    assert result["review_pack"]["version"] == "0.2"


# --- 3. Сломанный пакет — громкая ошибка ---------------------------------

def test_broken_yaml_is_an_error_not_a_silent_default():
    path = _write_policy("ceiling: [не список же\n")
    try:
        run_review.load_policy(path)
    except run_review.PolicyInvalid:
        pass
    else:
        raise AssertionError("сломанный yaml принят молча")
    finally:
        os.unlink(path)


def test_unknown_prompt_key_is_rejected():
    """Опечатка в ключе иначе означала бы тихую подстановку умолчания."""
    path = _write_policy(FULL_POLICY_YAML % (20, "recall", "b", "f", "d")
                         + "  fragmnet_quota: 'опечатка'\n")
    try:
        run_review.load_policy(path)
    except run_review.PolicyInvalid as e:
        assert "fragmnet_quota" in str(e), str(e)
    else:
        raise AssertionError("неизвестный ключ prompt принят")
    finally:
        os.unlink(path)


def test_unknown_bias_is_rejected():
    path = _full_policy(bias="whatever")
    try:
        run_review.load_policy(path)
    except run_review.PolicyInvalid as e:
        assert "whatever" in str(e), str(e)
    else:
        raise AssertionError("неизвестный bias принят")
    finally:
        os.unlink(path)


def test_boolean_ceiling_is_rejected():
    """bool — подкласс int: `ceiling: true` иначе стал бы потолком 1."""
    path = _full_policy(ceiling="true")
    try:
        run_review.load_policy(path)
    except run_review.PolicyInvalid:
        pass
    else:
        raise AssertionError("ceiling: true принят как число")
    finally:
        os.unlink(path)


def test_empty_prompt_text_is_rejected():
    """Пустая строка выкинула бы правило из промпта, не сказав об этом."""
    path = _full_policy(bias_text="   ")
    try:
        run_review.load_policy(path)
    except run_review.PolicyInvalid as e:
        assert "bias" in str(e), str(e)
    else:
        raise AssertionError("пустой текст правила принят")
    finally:
        os.unlink(path)


def test_custom_policy_text_reaches_the_prompt():
    """Смена политики в пакете меняет промпт — иначе вынос бессмыслен."""
    path = _full_policy(
        bias="precision",
        bias_text="Осторожность важнее полноты. Сомневаешься — молчи.",
        fragment_quota="Ориентир: не больше трёх замечаний на фрагмент.")
    try:
        policy = run_review.load_policy(path)
        assert policy["bias"] == "precision"
        prompt = run_review.PROMPT_DICT2.format(
            taxonomy="<T>", fragment="<F>", known_objects="<K>",
            glossary="<G>", conventions="<C>",
            policy_bias=policy["prompt"]["bias"],
            policy_quota=policy["prompt"]["fragment_quota"])
        assert "Осторожность важнее полноты. Сомневаешься — молчи." in prompt
        assert "Ориентир: не больше трёх замечаний на фрагмент." in prompt
        # Умолчания НЕ подмешались: ни одного следа recall-политики.
        assert "Сомневаешься — выдавай" not in prompt
        assert "от пяти до десяти замечаний" not in prompt
    finally:
        os.unlink(path)


def test_partial_policy_is_rejected():
    """Частичная политика — ошибка, а не «остальное возьмём по умолчанию».

    Блокер ревью: с наследованием умолчаний `bias: precision` без
    `prompt.bias` публиковал в результате «precision», отправляя модели
    recall-текст «сомневаешься — выдавай». Метка расходилась с применённой
    политикой, и наружу уходила метка.
    """
    path = _write_policy("bias: precision\nceiling: 10\n")
    try:
        run_review.load_policy(path)
    except run_review.PolicyInvalid as e:
        assert "prompt" in str(e), str(e)
    else:
        raise AssertionError("частичная политика принята")
    finally:
        os.unlink(path)


def test_unknown_top_level_key_is_rejected():
    """`ceilling: 5` (опечатка) иначе молча давал потолок 20."""
    path = _write_policy(FULL_POLICY_YAML % (20, "recall", "b", "f", "d")
                         + "ceilling: 5\n")
    try:
        run_review.load_policy(path)
    except run_review.PolicyInvalid as e:
        assert "ceilling" in str(e), str(e)
    else:
        raise AssertionError("неизвестный ключ верхнего уровня принят")
    finally:
        os.unlink(path)


def test_empty_policy_file_is_rejected():
    """Пустой файл, null и список иначе становились бы `{}` через `or {}`."""
    for body, label in (("", "пустой файл"), ("null\n", "null"),
                        ("[]\n", "список"), ("false\n", "false")):
        path = _write_policy(body)
        try:
            run_review.load_policy(path)
        except run_review.PolicyInvalid:
            pass
        else:
            raise AssertionError("%s принят как политика" % label)
        finally:
            os.unlink(path)


# --- 4. Пакет резолвится вместе с политикой ------------------------------

def test_resolve_pack_returns_policy_path():
    pack_id, version, tpl, dfx, glo, pol, warns = docreview.resolve_pack(
        "review-packs/mts-net/0.2")
    assert (pack_id, version) == ("mts-net", "0.2")
    assert pol and pol.endswith("policy.yaml") and os.path.isfile(pol)


def test_pack_without_policy_file_resolves_to_none():
    with tempfile.TemporaryDirectory() as d:
        base = os.path.join(d, "other-pack", "1.0")
        os.makedirs(base)
        _, _, _, _, _, pol, _ = docreview.resolve_pack(base)
        assert pol is None


def _make_pack(tmp, manifest, files=()):
    base = os.path.join(tmp, "p", "1.0")
    os.makedirs(base)
    with open(os.path.join(base, "pack.yaml"), "w", encoding="utf-8") as fh:
        fh.write(manifest)
    for name, body in files:
        with open(os.path.join(base, name), "w", encoding="utf-8") as fh:
            fh.write(body)
    return base


POLICY_BODY = FULL_POLICY_YAML % (20, "recall", "b", "f", "d")


def test_manifest_declared_policy_name_is_honoured():
    """Имя файла политики берётся из contents.policy, а не только по имени.

    Блокер ревью: резолвер искал фиксированный policy.yaml, поэтому пакет,
    объявивший другое имя, молча работал на умолчаниях.
    """
    with tempfile.TemporaryDirectory() as d:
        base = _make_pack(
            d, "id: p\nversion: '1.0'\ncontents:\n  policy: strict.yaml\n",
            [("strict.yaml", POLICY_BODY),
             ("policy.yaml", FULL_POLICY_YAML % (7, "precision", "x", "y", "z"))])
        _, _, _, _, _, pol, _ = docreview.resolve_pack(base)
        assert os.path.basename(pol) == "strict.yaml", pol
        # Читается именно объявленный файл, а не одноимённый по соглашению.
        assert run_review.load_policy(pol)["ceiling"] == 20


def test_manifest_declares_missing_policy_file_is_invalid():
    with tempfile.TemporaryDirectory() as d:
        base = _make_pack(
            d, "id: p\nversion: '1.0'\ncontents:\n  policy: absent.yaml\n")
        try:
            docreview.resolve_pack(base)
        except docreview.ReviewPackInvalid as e:
            assert "absent.yaml" in str(e), str(e)
        else:
            raise AssertionError("объявленный, но отсутствующий файл принят")


def test_manifest_policy_outside_pack_is_rejected():
    """Политика обязана жить внутри версионируемого пакета."""
    with tempfile.TemporaryDirectory() as d:
        for bad in ("../outside.yaml", "/etc/policy.yaml", "sub/dir.yaml"):
            base = _make_pack(
                d, "id: p\nversion: '1.0'\ncontents:\n  policy: %s\n" % bad)
            try:
                docreview.resolve_pack(base)
            except docreview.ReviewPackInvalid:
                pass
            else:
                raise AssertionError("путь наружу принят: %s" % bad)
            finally:
                import shutil
                shutil.rmtree(os.path.join(d, "p"))


def test_manifest_without_contents_falls_back_to_convention():
    with tempfile.TemporaryDirectory() as d:
        base = _make_pack(d, "id: p\nversion: '1.0'\n",
                          [("policy.yaml", POLICY_BODY)])
        _, _, _, _, _, pol, _ = docreview.resolve_pack(base)
        assert pol and os.path.basename(pol) == "policy.yaml"


def test_symlinked_policy_outside_pack_is_rejected():
    """Симлинк наружу — обход проверки имени, найден на ревью.

    `strict.yaml -> ../outside.yaml` проходит и проверку «это имя файла»,
    и `os.path.isfile`, после чего политика читается из неверсионируемого
    места — ровно того, от которого этот файл уводит.
    """
    with tempfile.TemporaryDirectory() as d:
        outside = os.path.join(d, "outside.yaml")
        with open(outside, "w", encoding="utf-8") as fh:
            fh.write(FULL_POLICY_YAML % (3, "precision", "X", "Y", "Z"))
        base = _make_pack(
            d, "id: p\nversion: '1.0'\ncontents:\n  policy: strict.yaml\n")
        os.symlink(outside, os.path.join(base, "strict.yaml"))
        try:
            docreview.resolve_pack(base)
        except docreview.ReviewPackInvalid as e:
            assert "пределы пакета" in str(e), str(e)
        else:
            raise AssertionError("симлинк за пределы пакета принят")


def test_conventional_policy_symlink_outside_pack_is_rejected():
    """Та же дыра там, где имя вообще не объявлено.

    Первая версия проверки realpath стояла ВНУТРИ ветки объявленного
    contents.policy, поэтому пакет без манифестного объявления с
    подложенным `policy.yaml -> ../outside.yaml` спокойно применял чужую
    политику. Воспроизведено: подгружался ceiling 3 вместо 20.
    """
    with tempfile.TemporaryDirectory() as d:
        outside = os.path.join(d, "outside.yaml")
        with open(outside, "w", encoding="utf-8") as fh:
            fh.write(FULL_POLICY_YAML % (3, "precision", "X", "Y", "Z"))
        base = _make_pack(d, "id: p\nversion: '1.0'\n")
        os.symlink(outside, os.path.join(base, "policy.yaml"))
        try:
            docreview.resolve_pack(base)
        except docreview.ReviewPackInvalid as e:
            assert "пределы пакета" in str(e), str(e)
        else:
            raise AssertionError("конвенциональный симлинк наружу принят")


def test_non_dict_contents_is_rejected():
    """`contents: строка` — сломанный манифест, а не отсутствие объявления."""
    with tempfile.TemporaryDirectory() as d:
        base = _make_pack(d, "id: p\nversion: '1.0'\ncontents: строка\n",
                          [("policy.yaml", POLICY_BODY)])
        try:
            docreview.resolve_pack(base)
        except docreview.ReviewPackInvalid as e:
            assert "contents" in str(e), str(e)
        else:
            raise AssertionError("несловарный contents принят")


def test_declared_null_policy_is_rejected():
    """`policy:` без значения — сломанное объявление, не его отсутствие.

    Иначе резолвер молча подставлял бы policy.yaml по соглашению, хотя
    манифест заявляет политику явно и заявляет её сломанно.
    """
    with tempfile.TemporaryDirectory() as d:
        base = _make_pack(d, "id: p\nversion: '1.0'\ncontents:\n  policy:\n",
                          [("policy.yaml", POLICY_BODY)])
        try:
            docreview.resolve_pack(base)
        except docreview.ReviewPackInvalid as e:
            assert "contents.policy" in str(e), str(e)
        else:
            raise AssertionError("contents.policy: null принят как отсутствие")


def test_contents_without_policy_key_uses_convention():
    """contents есть, policy в нём не объявлен — соглашение, это не ошибка."""
    with tempfile.TemporaryDirectory() as d:
        base = _make_pack(
            d, "id: p\nversion: '1.0'\ncontents:\n  defects: defects.yaml\n",
            [("policy.yaml", POLICY_BODY)])
        _, _, _, _, _, pol, _ = docreview.resolve_pack(base)
        assert pol and os.path.basename(pol) == "policy.yaml"


def test_non_string_keys_give_policy_error_not_crash():
    """YAML разрешает нестроковые ключи; они не должны падать TypeError.

    PolicyInvalid → REVIEW_PACK_INVALID (exit 4), а TypeError ушёл бы
    в общий обработчик и стал INTERNAL_ERROR: ошибка ПАКЕТА выглядела бы
    как поломка ядра.
    """
    cases = [
        ("ceiling: 20\nbias: recall\n1: сюрприз\n"
         "prompt:\n  bias: b\n  fragment_quota: f\n  document_quota: d\n",
         "нестроковый ключ верхнего уровня"),
        ("ceiling: 20\nbias: recall\n"
         "prompt:\n  bias: b\n  fragment_quota: f\n  document_quota: d\n"
         "  true: сюрприз\n", "нестроковый ключ в prompt"),
    ]
    for body, label in cases:
        path = _write_policy(body)
        try:
            run_review.load_policy(path)
        except run_review.PolicyInvalid:
            pass
        except Exception as e:                      # noqa: BLE001
            raise AssertionError("%s: %s вместо PolicyInvalid — в CLI это "
                                 "INTERNAL_ERROR" % (label, type(e).__name__))
        else:
            raise AssertionError("%s принят" % label)
        finally:
            os.unlink(path)


def test_shipped_pack_declares_its_policy_in_manifest():
    """Пакет 0.2 объявляет политику — иначе объявление было бы декоративным."""
    import yaml
    man = yaml.safe_load(open(os.path.join(PACK, "pack.yaml"), encoding="utf-8"))
    assert man["contents"]["policy"] == "policy.yaml"


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    for t in TESTS:
        t()
        print("ok  %s" % t.__name__)
    print("\n%d passed" % len(TESTS))
