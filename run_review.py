#!/usr/bin/env python3
"""
Раннер для анализа ТЗ.

Три режима:
  baseline  — наивный промпт «найди проблемы», без таксономии
  taxonomy  — прогон по типам дефектов из defects.yaml
  dict      — таксономия + словарь объектов документа + глоссарий терминов

Режим dict добавлен после слепой разметки 50 замечаний, которая показала:
таксономия сама по себе не поднимает долю полезных замечаний (60% против
56% у наивного промпта). Основные источники мусора оказались другими:

  1. Модель требует описать объект, который описан в соседнем фрагменте
     (7 случаев из 21). Лечится списком объектов, определённых в документе.
  2. Модель просит расшифровать отраслевые термины: DAG, IMEI, GPRS, IMSI
     (4 случая). Лечится глоссарием.
  3. Модель спорит с предметной областью (PS = packet switched).
     Лечится тем же глоссарием.
  4. Модель цитирует заголовки таблиц вместо содержательных строк.
     Лечится инструкцией в промпте.

Плюс жёсткая проверка: defect_id обязан быть из таксономии. В прогоне
без неё модель насочиняла около двадцати собственных ярлыков, из-за чего
одинаковые дефекты нельзя было склеить при дедупликации.

Использование:
    python3 run_review.py --doc vitrina.txt --mode dict
    python3 run_review.py --doc vitrina.txt --mode all

Зависимости: pip install requests pyyaml
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

import os

import requests
import yaml

# Эндпоинт модели берётся из окружения (в репозиторий адрес не коммитим).
# Пример: export OLLAMA_URL=http://<host>:11434/api/chat
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/chat")
MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:30b-a3b")
NUM_CTX = 32768
TIMEOUT = 900

# Допустимые значения важности. Модель обязана вернуть high/medium/low
# (см. промпт), но иногда возвращает смесь алфавитов — на реальном документе
# пришло «clarifiсатио» (латиница + кириллица). Такое значение проходило
# насквозь и молча становилось medium: и в контракте (_SEV_MAP в docreview),
# и в ранжировании (_SEV_WEIGHT). То есть замечание наименьшей важности
# показывалось как среднее, а на экране демо стояло нечитаемое слово.
SEVERITIES = ("critical", "high", "medium", "low", "clarification")

# Русские формы: модель изредка отвечает на языке документа.
_SEVERITY_RU = {"высок": "high", "средн": "medium", "низк": "low",
                "уточн": "clarification"}



SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            # Лимиты длины — не косметика: декодер обрезает значение ПО СИМВОЛАМ,
            # а не по смыслу. На реальном документе кейсодателя это стоило нам
            # и качества, и полноты: 4 из 13 замечаний обрывались на полуслове
            # («…определяет модель, а »), а одна цитата упёрлась ровно в 200
            # символов, из-за чего дословное сравнение не нашло её в тексте
            # и находка была отброшена как quote_not_found. Контракт приложения
            # длину этих полей не ограничивает (contracts/review-result.schema.json),
            # ограничение было целиком нашим. Запас взят с расчётом на самую
            # длинную строку таблицы в документах кейсодателя.
            # Цитата: 400. Лимит 200 обрезал длинные строки таблиц (в документах
            # кейсодателя строки до 228 символов), обрезанная цитата не находилась
            # дословно в тексте и находка отбрасывалась как quote_not_found —
            # измерено на реальном документе.
            # Объяснение и рекомендация: лимиты ВОЗВРАЩЕНЫ к 300/200. Подъём до
            # 700/500 измеренно стоил полноты (по месту 88% → 83%, слой модели
            # 82% → 74%): модель тратит бюджет на многословие вместо новых находок.
            # Обрыв текста на полуслове лечится не лимитом, а обрезкой по границе
            # предложения — см. trim_to_sentence.
            "quote": {"type": "string", "maxLength": 400},
            "defect_id": {"type": "string", "maxLength": 40},
            "explanation": {"type": "string", "maxLength": 300},
            "suggestion": {"type": "string", "maxLength": 200},
            # enum, а не maxLength: ограничение «не длиннее 12» обрезало
            # законное значение clarification (13 символов) прямо в декодере
            # модели — на реальном документе пришло «clarifiсатио», ровно
            # 12 символов из двух алфавитов. Словарь задаётся один раз в
            # SEVERITIES; normalize_severity остаётся вторым рубежом.
            "severity": {"type": "string", "enum": list(SEVERITIES)},
        },
        "required": ["quote", "defect_id", "explanation", "suggestion", "severity"],
    },
}

# Термины, которые в документации МТС не расшифровывают.
# Кейсодатель подтвердил: часть вещей опускается намеренно,
# потому что они общеизвестны внутри команды.
#
# ЗАМОРОЖЕНО. Эта константа обслуживает режимы baseline, taxonomy,
# dict и global — те, на которых получены измерения 56 / 60 / 59 / 83%.
# Ключи разметки в mark_findings.py — хэши от quote + explanation,
# поэтому любое изменение промпта или глоссария осиротит отметки
# и цифры перестанут воспроизводиться из файлов. Новые версии
# добавляются отдельными режимами (dict2), а не правкой этих.
#
# Режим dict2 читает глоссарий из glossary.yaml — см. load_glossary().
GLOSSARY = """
IMEI — идентификатор устройства, 15 цифр
IMSI — идентификатор абонента в сети
MSISDN — телефонный номер абонента
TAC — Type Allocation Code, первые 8 цифр IMEI, определяет модель устройства
LAC — Location Area Code, код зоны расположения
CELL_ID — идентификатор соты базовой станции
DAG — пайплайн обработки данных в Airflow
CDR — Call Detail Record, запись о телеком-событии
GPRS — пакетная передача данных в мобильной сети
PS — packet switched, пакетная коммутация (интернет-трафик)
MS — mobile switched, коммутация каналов (голос и SMS)
RAW, DDS, ADDS, CDM — слои хранилища данных
Kafka — брокер сообщений для потоковой передачи
ORC, Parquet — колоночные форматы хранения
upsert — вставка с обновлением существующих строк
партиция — секция таблицы, выделенная по значению поля
витрина — таблица для конечного потребителя данных
агрегат — таблица с предрассчитанной сводкой
справочник — таблица с постоянными значениями для обогащения
инкремент — загрузка только новых данных
бэкфилл — загрузка исторических данных за прошлые периоды
"""

# Типы дефектов, которые невозможно обнаружить в отдельном фрагменте:
# они требуют сопоставления удалённых друг от друга частей документа.
# Слепая разметка показала, что противоречие «Способ загрузки: Инкремент»
# против «Только полная перезагрузка месяца» пропускалось во всех прогонах
# именно потому, что утверждения попадали в разные фрагменты.
GLOBAL_TYPES = {
    "INTERNAL_CONTRADICTION",
    "SCHEMA_INCONSISTENCY",
    "INCOMPLETE_SCHEMA",
    "DANGLING_REFERENCE",
    "DUPLICATE_SEMANTICS",
    "RETENTION_GAP",
    "TIMEZONE_UNDEFINED",
    "TIMEZONE_INCONSISTENT",
    "BACKFILL_REFERENCE_HISTORY",
}

# Типы, которые по своей природе относятся к документу целиком, а не
# к конкретной строке: часовой пояс в документе один, регламент один,
# ключ целевой таблицы один. Экземпляры таких типов склеиваются
# независимо от того, как далеко друг от друга лежат цитаты.
#
# Основание: в прогоне режима full четыре замечания TIMEZONE_UNDEFINED
# и два NO_DEDUP_OR_KEY не склеились только потому, что цитаты были
# разбросаны по разделам и не попали в окно расстояния.
DOC_SCOPE_TYPES = {
    "TIMEZONE_UNDEFINED",
    "TIMEZONE_INCONSISTENT",
    "NO_SCHEDULE",
    "NO_VOLUME_ESTIMATE",
    "NO_DEDUP_OR_KEY",
    "RETENTION_GAP",
    "BACKFILL_REFERENCE_HISTORY",
    "NO_FILTER_DESCRIPTION",
    "INCOMPLETE_SCHEMA",
    "MISSING_SOURCE_LOCATION",
}

# Модель иногда рассуждает вслух прямо в объяснении и приходит к выводу,
# что места не является дефектом, но всё равно возвращает замечание.
SELF_NEGATION = (
    "не является дефектом",
    "это не дефект",
    "не подпадает под",
    "поэтому это не",
)

PROMPT_GLOBAL = """Ты ревьюишь техническое задание на разработку витрины или потока данных в телеком-компании.

Перед тобой ДОКУМЕНТ ЦЕЛИКОМ. Твоя задача — найти дефекты, которые видны только при взгляде на весь документ сразу: когда одно утверждение противоречит другому, когда объект упомянут, но нигде не описан, когда одно и то же названо по-разному в разных разделах.

ИЩИ ТОЛЬКО ЭТИ ТИПЫ ДЕФЕКТОВ:
{taxonomy}

НА ЧТО СМОТРЕТЬ В ПЕРВУЮ ОЧЕРЕДЬ:
1. Сопоставь раздел бизнес-требований с разделом требований к результату. Способ загрузки, регламент, правила обновления, глубина данных — не противоречат ли утверждения друг другу?
2. Собери все имена таблиц и полей, которые встречаются в алгоритме расчёта. Для каждого проверь: описана ли его структура где-нибудь в документе? Если объект используется, но нигде не описан — это дефект.
3. Сравни объявленные метрики и нефункциональные требования между собой.
4. Проверь, для всех ли перечисленных объектов заданы сроки хранения, регламент и объём.
5. Проверь, не названы ли одни и те же сущности по-разному в разных разделах и не описаны ли схожим образом два разных поля.

ОБЩЕИЗВЕСТНЫЕ ТЕРМИНЫ (расшифровывать не требуется):
{glossary}

ПРАВИЛА:
1. quote — дословная копия из документа, символ в символ. Для противоречия цитируй ОДНО из конфликтующих утверждений, а второе назови в explanation.
2. defect_id — строго один из списка выше.
3. explanation обязан называть обе стороны проблемы: что и чему противоречит, какой объект и где используется без описания.
4. Не выдумывай объекты, которых нет в документе.
5. Не дублируй: одна проблема — одно замечание.
6. Ориентир: от двух до шести замечаний на документ. Это дополнительный проход, основные дефекты уже найдены отдельно.

Верни только массив json, без пояснений.

ДОКУМЕНТ ЦЕЛИКОМ:
{document}"""

PROMPT_BASELINE = """Ты ревьюишь техническое задание на разработку витрины данных.

Найди в тексте места, которые могут быть непонятны разработчику или требуют уточнения.

Для каждого замечания верни:
- quote: точная дословная цитата из текста (копируй символ в символ)
- defect_id: короткое название типа проблемы
- explanation: почему это проблема
- suggestion: что уточнить или дополнить
- severity: high, medium или low

Верни только массив json, без пояснений.

ФРАГМЕНТ ТЕХНИЧЕСКОГО ЗАДАНИЯ:
{fragment}"""

PROMPT_TAXONOMY = """Ты ревьюишь техническое задание на разработку витрины или потока данных в телеком-компании.

Проверь фрагмент на наличие дефектов из списка ниже.

СПИСОК ТИПОВ ДЕФЕКТОВ:
{taxonomy}

КАК РАБОТАТЬ:
Пройди по списку типов сверху вниз и по каждому спроси себя: есть ли во фрагменте место, подпадающее под этот тип? Не останавливайся на первых найденных — проверь весь список до конца.

ПРАВИЛА:
1. quote должна быть дословной копией из фрагмента, символ в символ.
2. defect_id — строго один из id списка выше.
3. Полнота важнее осторожности. Пропущенная проблема хуже лишней придирки.
4. Ориентир: от трёх до восьми замечаний на фрагмент.
5. Цитата обязана быть настоящей. Выдумывать текст нельзя.
6. explanation — почему разработчик придёт с вопросом именно по этому месту.
7. suggestion — что конкретно дописать в документ.

Верни только массив json, без пояснений.

ФРАГМЕНТ ТЕХНИЧЕСКОГО ЗАДАНИЯ:
{fragment}"""

PROMPT_DICT = """Ты ревьюишь техническое задание на разработку витрины или потока данных в телеком-компании.

Проверь фрагмент на наличие дефектов из списка ниже.

СПИСОК ТИПОВ ДЕФЕКТОВ:
{taxonomy}

ОБЪЕКТЫ, ОПРЕДЕЛЁННЫЕ В ЭТОМ ДОКУМЕНТЕ:
{known_objects}

Ты видишь только один фрагмент, но документ больше. Все перечисленные выше объекты в документе ЕСТЬ и описаны — возможно, в другом разделе, которого ты сейчас не видишь. НЕ выдавай замечаний вида «объект не описан», «нет раздела со структурой», «не указано расположение» для объектов из этого списка. Если объекта в списке нет, а фрагмент на него ссылается — вот это дефект.

ОБЩЕИЗВЕСТНЫЕ ТЕРМИНЫ (расшифровывать в документе не требуется):
{glossary}

НЕ проси объяснить эти термины и не спорь с их значением. Аналитики и разработчики знают их без пояснений.

КАК РАБОТАТЬ:
Пройди по списку типов дефектов сверху вниз и по каждому спроси себя: есть ли во фрагменте место, подпадающее под этот тип? Проверь весь список до конца.

ПРАВИЛА:
1. quote — дословная копия из фрагмента, символ в символ.
2. Цитируй содержательную строку, а не заголовок таблицы, не название раздела и не одно имя поля. Цитата должна показывать проблему, а не указывать на неё пальцем.
3. defect_id — строго один из id списка типов. Свои идентификаторы не придумывай.
4. Полнота важнее осторожности. Пропущенная проблема хуже лишней придирки.
5. В suggestion не упоминай таблицы, поля и значения, которых нет в документе. Не выдумывай примеры вида CLUSTER_PROD или region_id.
6. Ориентир: от трёх до восьми замечаний на фрагмент.
7. explanation — почему разработчик придёт с вопросом именно по этому месту.

Верни только массив json, без пояснений.

ФРАГМЕНТ ТЕХНИЧЕСКОГО ЗАДАНИЯ:
{fragment}"""

# Версия 2 промпта для прохода по фрагментам. Отличия от PROMPT_DICT
# и основания для каждого:
#
# 1. Бюджет поднят с «3–8» до «5–10» на фрагмент. dict выдал 21
#    замечание на трёх фрагментах — модель упёрлась в потолок ориентира.
#    После дедупликации full даёт 12 при потолке кейсодателя 20:
#    восемь свободных мест при метрике «полнота».
#
# 2. Явно сказано не выбирать между типами. Прежний ориентир заставлял
#    модель конкурировать типы за слоты, и вылетали medium.
#
# 3. Запрет из словаря сужен. Прежняя формулировка глушила для имён
#    из списка не только «структура не описана», но и «не указано
#    расположение» и «остался плейсхолдер»: MISSING_SOURCE_LOCATION
#    и PLACEHOLDER_LEFT не сработали в full ни разу, при том что
#    в документе живой «Кластер: CLUSTER».
#
# 4. Добавлен блок соглашений компании из glossary.yaml с явным
#    различением обезличивания и заглушки — иначе соглашение
#    «TABLE_*/FIELD_* не плейсхолдеры» добивает PLACEHOLDER_LEFT.
PROMPT_DICT2 = """Ты ревьюишь техническое задание на разработку витрины или потока данных в телеком-компании.

Проверь фрагмент на наличие дефектов из списка ниже.

СПИСОК ТИПОВ ДЕФЕКТОВ:
{taxonomy}

ОБЪЕКТЫ, ОПРЕДЕЛЁННЫЕ В ЭТОМ ДОКУМЕНТЕ:
{known_objects}

Ты видишь только один фрагмент, но документ больше. Перечисленные выше объекты в документе упомянуты — возможно, в другом разделе, которого ты сейчас не видишь.

Что из этого следует и что НЕ следует:
- НЕ выдавай для объектов из списка замечаний о том, что объект не описан, не определён, отсутствует раздел с его структурой или перечнем полей. Их структура может быть описана в невидимом тебе разделе.
- Это единственное ограничение. Всё остальное про эти объекты проверяй как обычно: не указано расположение кластера или схемы, осталась заглушка вместо значения, не задан ключ, не описан граничный случай, противоречие с другим утверждением фрагмента — всё это дефекты, и наличие имени в списке ничего не отменяет.
- Если фрагмент ссылается на объект, которого в списке НЕТ, — это дефект.

ОБЩЕИЗВЕСТНЫЕ ТЕРМИНЫ (расшифровывать в документе не требуется):
{glossary}

НЕ проси объяснить эти термины и не спорь с их значением. Аналитики и разработчики знают их без пояснений.

СОГЛАШЕНИЯ КОМПАНИИ (не считать дефектами):
{conventions}

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
{fragment}"""

PROMPTS = {
    "baseline": PROMPT_BASELINE,
    "taxonomy": PROMPT_TAXONOMY,
    "dict": PROMPT_DICT,
    "dict2": PROMPT_DICT2,
}


def render_taxonomy(defects, only_ids=None):
    """Компактное описание типов дефектов для промпта."""
    lines = []
    for d in defects:
        if only_ids and d["id"] not in only_ids:
            continue
        hint = (d.get("detection_hint") or "").strip().replace("\n", " ")
        desc = (d.get("description") or "").strip().replace("\n", " ")
        line = f"- {d['id']} ({d['name']}, severity по умолчанию {d['severity']}): {desc}"
        if hint:
            line += f" Как искать: {hint}"
        lines.append(line)
    return "\n".join(lines)


def load_glossary(path):
    """
    Читает glossary.yaml и возвращает два блока текста: термины
    и соглашения компании.

    До этого глоссарий был захардкожен константой GLOSSARY: 22 термина
    против 39 в файле, и ни одного из соглашений. Заявленная
    расширяемость («три yaml подставляются под компанию, код не
    меняется») держалась на словах — файл лежал рядом и не читался.

    Возвращает (terms_text, conventions_text). Если файла нет,
    откатывается на константу, чтобы прогон не падал.
    """
    p = Path(path)
    if not p.exists():
        print(f"  !! {path} не найден, глоссарий из константы", file=sys.stderr)
        return GLOSSARY, ""

    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        # Глоссарий правит аналитик, а не разработчик. Одно двоеточие
        # внутри строки — валидная опечатка, ронять прогон трейсбеком
        # за неё нельзя: показываем место и работаем на константе.
        print(f"  !! {path}: ошибка разбора yaml, глоссарий из константы",
              file=sys.stderr)
        print(f"     {e}", file=sys.stderr)
        return GLOSSARY, ""

    terms = "\n".join(str(t) for t in data.get("terms", []))
    conventions = "\n".join(f"- {c}" for c in data.get("conventions", []))
    return terms, conventions


def load_taxonomy(path):
    """Возвращает (текст для промпта, множество id, список определений)."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    defects = data["defects"]
    ids = {d["id"] for d in defects}
    return render_taxonomy(defects), ids, defects


def extract_known_objects(text):
    """
    Вытаскивает из документа имена таблиц, полей и схем.
    Это и есть словарь: если объект встречается в документе,
    значит он в нём определён, и жаловаться на его отсутствие не надо.
    """
    names = set(re.findall(r"\b(?:TABLE|FIELD|SCHEMA|TOPIC)_[A-Z0-9_]+\b", text))
    names |= set(re.findall(r"\b(?:lac|cell_id|cell|tac|imei|imsi|region_code|region_name|vendor_name)\b",
                            text, flags=re.IGNORECASE))
    return "\n".join(sorted(names))


def _split_long_block(block, max_chars):
    """Делит блок, который сам по себе длиннее предела.

    Нужен для документов из настоящего Word: там между абзацами нет пустых
    строк, и весь документ приходит одним блоком. Без этого фрагмент уезжал
    в модель в десяток раз больше проектного — то есть в режиме, на котором
    не снята ни одна наша метрика.

    Режем по границам строк, а не по символам: строка — это абзац или ячейка
    таблицы, и разрывать её посередине значит ломать цитату.
    """
    if len(block) <= max_chars:
        return [block]
    pieces, current = [], ""
    for line in block.split("\n"):
        if current and len(current) + len(line) + 1 > max_chars:
            pieces.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
        # Одна строка длиннее предела (например, широкая таблица одной
        # строкой) — режем её жёстко, иначе предел снова не соблюдён.
        while len(current) > max_chars:
            pieces.append(current[:max_chars])
            current = current[max_chars:]
    if current.strip():
        pieces.append(current)
    return [p for p in pieces if p.strip()]


def split_document(text, max_chars=1500, min_chars=200):
    """Режет документ на фрагменты по пустым строкам, склеивая мелкие блоки."""
    raw_blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    blocks = []
    for b in raw_blocks:
        blocks.extend(_split_long_block(b, max_chars))
    fragments, current = [], ""

    for b in blocks:
        # +2 — разделитель "\n\n", который добавит склейка ниже. Без него
        # два блока по 750 символов дают фрагмент 1502 при пределе 1500.
        if current and len(current) + len(b) + 2 > max_chars:
            fragments.append(current.strip())
            current = b
        else:
            current = f"{current}\n\n{b}" if current else b

    if current.strip():
        fragments.append(current.strip())

    merged = []
    for f in fragments:
        # Мелкий хвост приклеиваем к предыдущему, но только если склейка не
        # выходит за предел: иначе борьба с мелкими фрагментами порождала бы
        # слишком крупные, ровно то, от чего мы уходим выше.
        if merged and len(f) < min_chars and len(merged[-1]) + len(f) + 2 <= max_chars:
            merged[-1] = merged[-1] + "\n\n" + f
        else:
            merged.append(f)

    return merged


PUNCT = r"[|\u2014\u2013\-–—:;,.()\[\]«»\"'`*_/\\]"


def normalize(s):
    """Убирает разделители таблиц, пунктуацию и лишние пробелы."""
    s = re.sub(PUNCT, " ", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def loose_match(quote, source):
    """Слова цитаты идут в исходнике в том же порядке с небольшими вставками."""
    words = [w for w in normalize(quote).split() if len(w) > 1]
    if len(words) < 3:
        return False
    pattern = r"\W+(?:\w+\W+){0,3}?".join(re.escape(w) for w in words)
    return re.search(pattern, normalize(source)) is not None


def trim_to_sentence(text, cap):
    """Если текст упёрся в лимит длины и оборван на полуслове — обрезать по
    последней законченной мысли.

    Декодер модели останавливается по символам, поэтому в выдаче попадались
    хвосты вида «…определяет модель, а ». Аналитику полезнее короткая целая
    фраза, чем длинная оборванная. Режем по последней точке; если её нет —
    по последнему пробелу с многоточием, чтобы обрыв был виден явно.
    Тексты, не упёршиеся в лимит, не трогаем.
    """
    t = (text or "").strip()
    if len(t) > cap:                       # сам лимит тоже соблюдаем: декодер
        t = t[:cap].rstrip()               # его держит, но функция не должна
    if len(t) < cap - 5 or t.endswith((".", "!", "?", "»", "'", '"', ")")):
        return t                           # полагаться на это молча
    cut = max(t.rfind(". "), t.rfind("! "), t.rfind("? "))
    if cut > cap // 3:
        return t[:cut + 1]
    cut = t.rfind(" ")
    return (t[:cut].rstrip(" ,;:—-") + "…") if cut > 0 else t


def normalize_severity(value):
    """(значение из словаря, было_ли_исправлено).

    Порядок: точное совпадение → однозначный ASCII-префикс (так «clarifiсатио»
    становится clarification) → русская форма → medium как безопасный запас.
    Замечание из-за важности НЕ отбрасывается: важность — не основание
    сомневаться в самой находке.
    """
    s = re.sub(r"[\s.,;:]+", "", str(value or "")).lower()
    if s in SEVERITIES:
        return s, False
    prefix = re.match(r"[a-z]*", s).group(0)
    if len(prefix) >= 3:
        hits = [x for x in SEVERITIES if x.startswith(prefix)]
        if len(hits) == 1:
            return hits[0], True
    for ru, sev in _SEVERITY_RU.items():
        if s.startswith(ru):
            return sev, True
    return "medium", True


def verify(findings, source, valid_ids):
    """
    Проверяет замечания: цитата должна существовать в тексте,
    defect_id — принадлежать таксономии (если она задана).
    Возвращает (принятые, отброшенные с причиной).
    """
    src = normalize(source)
    kept, dropped = [], []

    for f in findings:
        raw_quote = f.get("quote", "")
        q = normalize(raw_quote)

        if len(q) < 8:
            f["reject_reason"] = "too_short"
            dropped.append(f)
            continue

        if not (q in src or loose_match(raw_quote, source)):
            f["reject_reason"] = "quote_not_found"
            dropped.append(f)
            continue

        if valid_ids and f.get("defect_id") not in valid_ids:
            f["reject_reason"] = f"unknown_defect_id:{f.get('defect_id')}"
            dropped.append(f)
            continue

        expl = f.get("explanation", "").lower()
        if any(marker in expl for marker in SELF_NEGATION):
            f["reject_reason"] = "self_negated"
            dropped.append(f)
            continue

        f["explanation"] = trim_to_sentence(f.get("explanation"), 300)
        f["suggestion"] = trim_to_sentence(f.get("suggestion"), 200)

        sev, corrected = normalize_severity(f.get("severity"))
        if corrected:
            f["severity_raw"] = f.get("severity")   # для отчёта и разбора
        f["severity"] = sev

        kept.append(f)

    return kept, dropped


def ask_model(prompt):
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "think": False,
        "format": SCHEMA,
        "options": {"num_ctx": NUM_CTX, "temperature": 0,
                    "num_predict": 4096},
        "keep_alive": "2h",
    }
    r = requests.post(OLLAMA_URL, json=payload, timeout=TIMEOUT)
    r.raise_for_status()
    content = r.json()["message"]["content"]
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        print("  !! невалидный json, фрагмент пропущен", file=sys.stderr)
        return []


def run(doc_text, mode, taxonomy_text, valid_ids, known_objects,
        glossary_text=None, conventions_text=""):
    fragments = split_document(doc_text)
    print(f"[{mode}] фрагментов: {len(fragments)}")

    # По умолчанию — замороженная константа: режимы dict, taxonomy
    # и baseline должны воспроизводить измеренные прогоны.
    glossary_text = GLOSSARY if glossary_text is None else glossary_text

    all_kept, all_dropped = [], []
    t0 = time.time()

    # у наивного промпта своей таксономии нет, проверять id не по чему
    ids_to_check = set() if mode == "baseline" else valid_ids

    for i, frag in enumerate(fragments, 1):
        tpl = PROMPTS[mode]
        if mode == "baseline":
            prompt = tpl.format(fragment=frag)
        elif mode == "taxonomy":
            prompt = tpl.format(taxonomy=taxonomy_text, fragment=frag)
        elif mode == "dict2":
            prompt = tpl.format(taxonomy=taxonomy_text, fragment=frag,
                                known_objects=known_objects,
                                glossary=glossary_text,
                                conventions=conventions_text)
        else:
            prompt = tpl.format(taxonomy=taxonomy_text, fragment=frag,
                                known_objects=known_objects,
                                glossary=glossary_text)

        ts = time.time()
        findings = ask_model(prompt)
        kept, dropped = verify(findings, frag, ids_to_check)
        dt = time.time() - ts

        print(f"  фрагмент {i}/{len(fragments)}: "
              f"найдено {len(findings)}, принято {len(kept)}, {dt:.1f} с")

        all_kept.extend(kept)
        all_dropped.extend(dropped)

    reasons = {}
    for d in all_dropped:
        key = d.get("reject_reason", "?").split(":")[0]
        reasons[key] = reasons.get(key, 0) + 1

    return {
        "mode": mode,
        "fragments": len(fragments),
        "total_seconds": round(time.time() - t0, 1),
        "found_raw": len(all_kept) + len(all_dropped),
        "verified": len(all_kept),
        "rejected_count": len(all_dropped),
        "reject_reasons": reasons,
        "severity_fixed": sum(1 for f in all_kept if "severity_raw" in f),
        "findings": all_kept,
        "rejected": all_dropped,
    }


# Во сколько символов документа обходится одна единица окна модели.
# Оценка грубая и намеренно консервативная: на кириллице токенизатор даёт
# примерно 2.5 символа на токен, часть окна занимают инструкция, таксономия
# и ответ. Нужна не точность, а честный сигнал «документ не поместился».
GLOBAL_DOC_CHARS_PER_CTX = 2.0


def global_doc_char_budget():
    """Бюджет символов для кросс-фрагментного прохода.

    Считается в момент вызова, а не при импорте: `NUM_CTX` переопределяется
    из model-config уже после загрузки модуля. Константа, снятая на импорте,
    осталась бы от значения по умолчанию — и при меньшем реальном окне
    вернулась бы та самая молчаливая обрезка, от которой мы уходим.
    """
    return int(NUM_CTX * GLOBAL_DOC_CHARS_PER_CTX)


def run_global(doc_text, defects, glossary_text):
    """
    Один вызов на весь документ. Ищет только те типы дефектов,
    которые требуют сопоставления удалённых частей текста.

    Возвращает (kept, truncated_chars): второе — сколько символов не
    поместилось в окно модели. Молча анализировать кусок и отдавать это как
    проход по всему документу нельзя: кросс-фрагментные типы именно тем и
    ценны, что сопоставляют удалённые части, а на обрезанном документе
    половины сопоставлений просто нет.
    """
    subset = GLOBAL_TYPES & {d["id"] for d in defects}
    taxonomy_text = render_taxonomy(defects, subset)

    budget = global_doc_char_budget()
    truncated = max(0, len(doc_text) - budget)
    if truncated:
        doc_text = doc_text[:budget]
        print(f"[global] ВНИМАНИЕ: документ длиннее окна модели, "
              f"в кросс-фрагментный проход ушли первые "
              f"{budget} символов, не поместилось {truncated}")

    print(f"[global] один проход по документу, типов в поиске: {len(subset)}")

    t0 = time.time()
    prompt = PROMPT_GLOBAL.format(taxonomy=taxonomy_text,
                                  glossary=glossary_text,
                                  document=doc_text)
    findings = ask_model(prompt)
    kept, dropped = verify(findings, doc_text, subset)
    dt = time.time() - t0

    print(f"  найдено {len(findings)}, принято {len(kept)}, {dt:.1f} с")

    reasons = {}
    for d in dropped:
        key = d.get("reject_reason", "?").split(":")[0]
        reasons[key] = reasons.get(key, 0) + 1

    return {
        "mode": "global",
        "fragments": 1,
        "total_seconds": round(dt, 1),
        "found_raw": len(kept) + len(dropped),
        "verified": len(kept),
        "rejected_count": len(dropped),
        "reject_reasons": reasons,
        "severity_fixed": sum(1 for f in kept if "severity_raw" in f),
        "findings": kept,
        "rejected": dropped,
        "truncated_chars": truncated,
    }


def quote_position(quote, source):
    """Позиция цитаты в документе — нужна, чтобы понять, близко ли лежат
    два замечания одного типа."""
    q, src = normalize(quote), normalize(source)
    return src.find(q) if q in src else -1


def content_score(finding):
    """
    Насколько цитата содержательна. Считаем слова длиннее двух букв:
    цитата «Инкремент» проигрывает цитате «Обновление | Только полная
    перезагрузка месяца (без upsert)», хотя обе про один дефект.
    Раньше выбор шёл по длине строки, и дважды побеждал худший экземпляр.
    """
    words = [w for w in normalize(finding.get("quote", "")).split() if len(w) > 2]
    return len(words)


def dedupe(findings, doc_text, window=500):
    """
    Склеивает замечания об одной и той же проблеме.

    Правило: совпадает defect_id И цитаты либо лежат в документе ближе
    чем на window символов, либо одна содержится в другой.
    Из группы остаётся замечание с самой длинной цитатой — она полнее
    показывает проблему; при равных цитатах берётся более подробное
    объяснение.

    Основание: слепая разметка показала, что из 13 полезных замечаний
    уникальных проблем около 12, а среди бесполезных 4 из 9 были
    повторами. При бюджете аналитика в 10-15 замечаний дубли съедают
    места, которые должны достаться другим дефектам.
    """
    enriched = []
    for f in findings:
        f = dict(f)
        f["_pos"] = quote_position(f.get("quote", ""), doc_text)
        f["_qn"] = normalize(f.get("quote", ""))
        enriched.append(f)

    groups = {}
    for f in enriched:
        groups.setdefault(f.get("defect_id", "?"), []).append(f)

    kept, merged = [], []

    for _, group in groups.items():
        group.sort(key=lambda x: x["_pos"])
        clusters = []
        for f in group:
            placed = False
            doc_scope = f.get("defect_id") in DOC_SCOPE_TYPES
            for cl in clusters:
                for other in cl:
                    near = (f["_pos"] >= 0 and other["_pos"] >= 0
                            and abs(f["_pos"] - other["_pos"]) <= window)
                    nested = f["_qn"] in other["_qn"] or other["_qn"] in f["_qn"]
                    if doc_scope or near or nested:
                        cl.append(f)
                        placed = True
                        break
                if placed:
                    break
            if not placed:
                clusters.append([f])

        for cl in clusters:
            cl.sort(key=lambda x: (content_score(x),
                                   len(x.get("explanation", ""))),
                    reverse=True)
            best = cl[0]
            best["merged_count"] = len(cl)
            if len(cl) > 1:
                merged.extend(cl[1:])
            kept.append(best)

    for f in kept:
        f.pop("_pos", None)
        f.pop("_qn", None)
    for f in merged:
        f.pop("_pos", None)
        f.pop("_qn", None)

    # порядок — через _sev_rank, а не через свою копию таблицы: копия не знала
    # про critical и ставила его в один ряд с medium
    kept.sort(key=_sev_rank)

    return kept, merged


BUDGET_CEILING = 20  # потолок замечаний на документ (ориентир кейсодателя)


def _sev_rank(f):
    """Класс защиты от бюджета: 0 — не режем (critical и high), дальше по убыванию.
    critical и high в ОДНОМ классе намеренно: docreview._rank_union считает
    защищёнными именно ранг 0, и развести их значило бы снять защиту с high."""
    return {"critical": 0, "high": 0, "medium": 1, "low": 2}.get(
        f.get("severity", "medium"), 1)


# Вес важности внутри класса: critical выше high, чтобы при равной уверенности
# он шёл первым в выдаче. Значения словаря SEVERITIES покрыты полностью —
# иначе новое значение молча получало бы вес medium.
_SEV_WEIGHT = {"critical": 4, "high": 3, "medium": 2, "low": 1,
               "clarification": 1}


def _priority(f):
    """severity × confidence — произведение веса важности на уверенность.
    Уверенность = согласие проходов (merged_count): замечание, к которому
    сошлось несколько проходов, вероятнее реально. Произведение (а не строгий
    приоритет severity) позволяет уверенному low обойти едва замеченный medium —
    пропуск реального дефекта хуже придирки. Содержательность цитаты — тай-брейк.
    Модель не вызывается, схема не расширяется: оба сигнала есть после дедупа."""
    sev = _SEV_WEIGHT.get(f.get("severity", "medium"), 2)
    return (sev * f.get("merged_count", 1), content_score(f))


def apply_budget(kept, ceiling=BUDGET_CEILING):
    """Ранжирование и отсечение при переполнении бюджета.

    high НЕ режется никогда: сначала берём все high-замечания, затем добираем
    medium/low по убыванию severity × confidence до потолка. Если одних high
    больше потолка — оставляем их все (полнота важных дефектов приоритетнее
    бюджета). При наборе в пределах потолка возвращаем вход без изменений.
    Возвращает (оставленные, отсечённые).
    """
    if len(kept) <= ceiling:
        return kept, []
    high = [f for f in kept if _sev_rank(f) == 0]
    rest = [f for f in kept if _sev_rank(f) != 0]
    # Внутри защищённого класса тоже упорядочиваем по важности: там лежат
    # и critical, и high, и без сортировки critical оказывался ниже high
    # просто по порядку поступления.
    high.sort(key=lambda f: _priority(f), reverse=True)
    rest.sort(key=lambda f: _priority(f), reverse=True)
    slots = max(0, ceiling - len(high))
    # Защищённые впереди (не режутся), затем rest в порядке severity × confidence.
    # Финальную пересортировку по severity НЕ делаем — она бы отменила ранг.
    keep = high + rest[:slots]
    dropped = rest[slots:]
    return keep, dropped


def run_full(doc_text, defects, taxonomy_text, valid_ids, known_objects,
             frag_mode="dict", glossary_text=None, conventions_text="",
             label="full"):
    """
    Продуктовый режим: проход по фрагментам плюс проход по документу
    целиком, затем дедупликация.

    frag_mode задаёт промпт прохода по фрагментам. Глобальный проход
    намеренно НЕ параметризован и всегда идёт на замороженной константе
    GLOSSARY: тогда разница между full и full2 объясняется только
    изменением промпта фрагментов, а не двумя правками сразу.
    """
    frag = run(doc_text, frag_mode, taxonomy_text, valid_ids, known_objects,
               glossary_text=glossary_text, conventions_text=conventions_text)
    glob = run_global(doc_text, defects, GLOSSARY)

    # Детерминированные типы принадлежат формальному слою (check_formal): он их
    # ловит точнее и без галлюцинаций. Находки этих типов из модели отбрасываем,
    # чтобы не было межслойного дубля и модельных ложных срабатываний.
    det_ids = {d["id"] for d in defects
               if d.get("detectable_by") == "deterministic"}
    combined = [f for f in (frag["findings"] + glob["findings"])
                if f.get("defect_id") not in det_ids]
    kept, merged = dedupe(combined, doc_text)
    kept, capped = apply_budget(kept)

    print(f"[{label}] до дедупликации {len(combined)}, после дедупа "
          f"{len(kept) + len(capped)}, склеено {len(merged)}, "
          f"отсечено бюджетом {len(capped)}, итог {len(kept)}")

    return {
        "mode": label,
        "fragments": frag["fragments"],
        "total_seconds": round(frag["total_seconds"] + glob["total_seconds"], 1),
        "found_raw": frag["found_raw"] + glob["found_raw"],
        "verified": len(kept),
        "before_dedupe": len(combined),
        "merged_away": len(merged),
        "capped_away": len(capped),
        "rejected_count": frag["rejected_count"] + glob["rejected_count"],
        "reject_reasons": {**frag["reject_reasons"], **glob["reject_reasons"]},
        # Сколько символов не поместилось в кросс-фрагментный проход.
        # Ноль — документ прошёл целиком.
        "truncated_chars": glob.get("truncated_chars", 0),
        "severity_fixed": sum(1 for f in kept if "severity_raw" in f),
        "findings": kept,
        "merged": merged,
        "capped": capped,
        "rejected": frag["rejected"] + glob["rejected"],
    }


def summarize(res):
    raw, ver = res["found_raw"], res["verified"]
    share = f"{ver / raw * 100:.0f}%" if raw else "—"
    print(f"\n=== {res['mode']} ===")
    print(f"  фрагментов:         {res['fragments']}")
    print(f"  замечаний выдано:   {raw}")
    if "before_dedupe" in res:
        print(f"  до дедупликации:    {res['before_dedupe']}")
        print(f"  склеено дублей:     {res['merged_away']}")
    print(f"  принято:            {ver} ({share})")
    print(f"  отброшено:          {res['rejected_count']}")
    if res.get("severity_fixed"):
        print(f"  важность исправлена: {res['severity_fixed']} "
              f"(модель вернула значение вне словаря)")
    for k, v in sorted(res["reject_reasons"].items(), key=lambda x: -x[1]):
        print(f"      {k}: {v}")
    print(f"  время:              {res['total_seconds']} с")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc", required=True)
    ap.add_argument("--defects", default="defects.yaml")
    ap.add_argument("--glossary", default="glossary.yaml")
    ap.add_argument("--mode", default="dict",
                    choices=["baseline", "taxonomy", "dict", "global",
                             "full", "dict2", "full2", "all", "v2"])
    ap.add_argument("--out", default="results")
    args = ap.parse_args()

    doc_text = Path(args.doc).read_text(encoding="utf-8")
    taxonomy_text, valid_ids, defects = load_taxonomy(args.defects)
    known_objects = extract_known_objects(doc_text)
    terms_text, conventions_text = load_glossary(args.glossary)

    print(f"Объектов в словаре: {len(known_objects.splitlines())}")
    print(f"Терминов в глоссарии: {len(terms_text.splitlines())}, "
          f"соглашений: {len(conventions_text.splitlines())}")

    if args.mode == "all":
        modes = ["baseline", "taxonomy", "dict", "global", "full"]
    elif args.mode == "v2":
        modes = ["dict2", "full2"]
    else:
        modes = [args.mode]

    outdir = Path(args.out)
    outdir.mkdir(exist_ok=True)

    results = []
    for m in modes:
        if m == "global":
            res = run_global(doc_text, defects, GLOSSARY)
        elif m == "full":
            res = run_full(doc_text, defects, taxonomy_text,
                           valid_ids, known_objects)
        elif m == "full2":
            res = run_full(doc_text, defects, taxonomy_text,
                           valid_ids, known_objects,
                           frag_mode="dict2",
                           glossary_text=terms_text,
                           conventions_text=conventions_text,
                           label="full2")
        elif m == "dict2":
            res = run(doc_text, m, taxonomy_text, valid_ids, known_objects,
                      glossary_text=terms_text,
                      conventions_text=conventions_text)
        else:
            res = run(doc_text, m, taxonomy_text, valid_ids, known_objects)
        results.append(res)
        path = outdir / f"{Path(args.doc).stem}_{m}.json"
        path.write_text(json.dumps(res, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        print(f"  сохранено: {path}")

    for r in results:
        summarize(r)

    print("\n  Дальше: python3 mark_findings.py --doc "
          f"{Path(args.doc).stem} --modes {','.join(modes)}")


if __name__ == "__main__":
    main()
