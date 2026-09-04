#!/usr/bin/env python3
"""Тесты фиксов формального слоя (пункт 4): устранение ложных срабатываний
nullability (таблица источников, списки полей) и hdfs (заголовок раздела).

Запуск: python test_check_formal.py
"""
import glob
import check_formal as cf

CFG = cf.load_config("template.yaml")

RECV = ("Приемники. Таблица: SCHEMA_X.TABLE_Y\n"
        "Атрибут | Тип данных | Описание атрибута | Обязательность | Источник\n")
SRC = ("Источники. Таблица: TABLE_RAW\n"
       "Атрибут | Тип данных | Комментарий\n")


def test_nullability_flags_receiver_row_without_marker():
    text = RECV + "FIELD_X | string | Описание | — | Источник\n"
    ids = [f["defect_id"] for f in cf.check_nullability(text, CFG)]
    assert "NULLABILITY_UNSPECIFIED" in ids


def test_nullability_ok_when_marker_present():
    text = RECV + "FIELD_X | string | Описание | NOT NULL | Источник\n"
    assert cf.check_nullability(text, CFG) == []


def test_nullability_ignores_source_table():
    # у таблицы источников нет колонки обязательности по шаблону — не FP
    text = SRC + "FIELD_IMSI | string | Идентификатор абонента\n"
    assert cf.check_nullability(text, CFG) == []


def test_nullability_ignores_example_field_list():
    text = "Пример данных\nFIELD_A | FIELD_B | FIELD_C\n1 | 2 | 3\n"
    assert cf.check_nullability(text, CFG) == []


def test_nullability_flags_when_column_removed_entirely():
    # колонка «Обязательность» удалена из заголовка — дефект, не пропуск
    text = ("Приемники. Таблица: SCHEMA_X.TABLE_Y\n"
            "Атрибут | Тип данных | Описание атрибута | Источник\n"
            "FIELD_X | string | Описание | Источник\n")
    ids = [f["defect_id"] for f in cf.check_nullability(text, CFG)]
    assert "NULLABILITY_UNSPECIFIED" in ids


def test_nullability_description_word_does_not_mask_empty_cell():
    # «необязательный» в ОПИСАНИИ не должно скрывать пустую ячейку обязательности
    text = RECV + "FIELD_X | string | необязательный параметр | — | Источник\n"
    ids = [f["defect_id"] for f in cf.check_nullability(text, CFG)]
    assert "NULLABILITY_UNSPECIFIED" in ids, "маркер ищется в ячейке колонки, не в описании"


def test_nullability_marker_in_correct_cell_ok():
    text = RECV + "FIELD_X | string | описание поля | NULLABLE | Источник\n"
    assert cf.check_nullability(text, CFG) == []


def test_hdfs_alternative_phrasings_without_format():
    for line in ("HDFS: /data/cdm/x",
                 "Расположение в HDFS: /data/cdm/x",
                 "Директория HDFS: /data/cdm/x",
                 "Хранилище HDFS: /data/cdm/x"):
        ids = [f["defect_id"] for f in cf.check_hdfs(line + "\n", CFG)]
        assert "HDFS_PATH_INCOMPLETE" in ids, f"не поймано: {line}"


def test_hdfs_ignores_partition_section_header():
    text = "Формирование ключа (kafka) / партиции (hdfs)\nПоле партиции: FIELD_BIZ_DATE\n"
    assert cf.check_hdfs(text, CFG) == []


def test_hdfs_line_starting_with_other_alias_still_flagged():
    # content-строка начинается со слова-alias другого раздела, но это не заголовок
    for line in ("Структура HDFS: /data/cdm/x", "Схема данных HDFS: /data/cdm/x"):
        ids = [f["defect_id"] for f in cf.check_hdfs(line + "\n", CFG)]
        assert "HDFS_PATH_INCOMPLETE" in ids, f"ложный пропуск: {line}"


def test_hdfs_partition_header_with_numbering_or_markdown_excluded():
    base = "Формирование ключа (kafka) / партиции (hdfs)"
    for hdr in (f"2. {base}", f"2.1 {base}", f"2.1.3 {base}",
                f"## {base}", f"**{base}**", f"3) {base}"):
        assert cf.is_section_header(hdr, CFG), f"не распознан заголовок: {hdr}"
        assert cf.check_hdfs(hdr + "\n", CFG) == [], f"ложный дефект: {hdr}"


def test_strip_numbering_variants():
    assert cf.strip_numbering("2. Структура") == "Структура"
    assert cf.strip_numbering("2.1 Структура") == "Структура"
    assert cf.strip_numbering("## Структура") == "Структура"
    assert cf.strip_numbering("**Структура**") == "Структура"
    assert cf.strip_numbering("2.1.3 Структура") == "Структура"
    assert cf.strip_numbering("2) Структура") == "Структура"
    assert cf.strip_numbering("Структура") == "Структура"
    # строки-данные не должны калечиться
    assert cf.strip_numbering("2G, 3G, 4G") == "2G, 3G, 4G"
    assert cf.strip_numbering("2024 Команда") == "2024 Команда"   # число без разделителя
    assert cf.strip_numbering("SELECT *") == "SELECT *"           # непарная звезда
    assert cf.strip_numbering("FIELD_*") == "FIELD_*"
    assert cf.strip_numbering("Команда*") == "Команда*"           # непарная
    assert cf.strip_numbering("#Команда") == "#Команда"           # # без пробела — не заголовок
    assert cf.strip_numbering("* Команда") == "* Команда"         # маркер списка, не жирный
    # асимметричные звёзды не должны калечиться
    assert cf.strip_numbering("***Команда**") == "***Команда**"
    assert cf.strip_numbering("**Команда*") == "**Команда*"
    assert cf.strip_numbering("*Команда**") == "*Команда**"
    assert cf.strip_numbering("**Команда**") == "Команда"         # парный — снимается


def test_hdfs_flags_path_without_format():
    text = "Путь хранения в HDFS: Папка.\n"
    ids = [f["defect_id"] for f in cf.check_hdfs(text, CFG)]
    assert "HDFS_PATH_INCOMPLETE" in ids


def test_hdfs_ok_with_path_and_format():
    text = "Путь хранения в HDFS: /data/cdm/x, формат ORC.\n"
    assert cf.check_hdfs(text, CFG) == []


def test_vague_wording_flags_loophole():
    text = "Алгоритм обработки потока\nДанные обновляются по возможности.\n"
    ids = [f["defect_id"] for f in cf.check_vague_wording(text, CFG)]
    assert "VAGUE_WORDING" in ids


def test_vague_wording_flags_open_ended():
    text = "Перечень справочников: TABLE_REGION_REF, TABLE_RAT_REF и т.д.\n"
    ids = [f["defect_id"] for f in cf.check_vague_wording(text, CFG)]
    assert "VAGUE_WORDING" in ids


def test_vague_wording_quote_is_verbatim():
    text = "Обработка выполняется при необходимости повторно.\n"
    fs = cf.check_vague_wording(text, CFG)
    assert fs and fs[0]["quote"] in text          # цитата дословна
    assert fs[0]["severity"] == "low"


def test_vague_wording_all_configured_phrases_flagged():
    # каждая фраза из словаря должна ловиться — чтобы правки конфига не оставались слепыми
    cats = CFG["vague_wording"]["categories"]
    for cat, phrases in cats.items():
        for p in phrases:
            line = f"Обработка выполняется {p} по регламенту.\n"
            ids = [f["defect_id"] for f in cf.check_vague_wording(line, CFG)]
            assert "VAGUE_WORDING" in ids, f"не поймано: {cat}/{p!r}"


def test_vague_wording_no_fp_on_negation_verb():
    # идиома «не ограничиваясь» убрана из словаря (FP-склонна) → эти строки чисты
    text = ("Формат не ограничивает размер файла.\n"
            "Размер файла зависит от формата, но не ограничивается им.\n"
            "Система не ограничивает число включаемых файлов.\n")
    assert cf.check_vague_wording(text, CFG) == []


def test_vague_wording_spacing_variant():
    text = "Перечень: TABLE_A, TABLE_B и т. д.\n"
    ids = [f["defect_id"] for f in cf.check_vague_wording(text, CFG)]
    assert "VAGUE_WORDING" in ids


def test_vague_wording_no_fp_on_technical_comparators():
    # «выше», «больше», «наибольшее» — легитимный тех.смысл, НЕ должны срабатывать
    text = ("Порог: больше 100 сообщений.\nСм. пункт выше.\n"
            "Берётся наибольшее значение агрегата.\n")
    assert cf.check_vague_wording(text, CFG) == []


def test_no_filter_flags_empty_filter_step():
    text = ("Алгоритм обработки потока\n"
            "Шаг 1. Фильтрация данных\n"
            "Шаг 2. Обогащение данных\n"
            "Обогащение справочником.\n")
    ids = [f["defect_id"] for f in cf.check_no_filter(text, CFG)]
    assert "NO_FILTER_DESCRIPTION" in ids


def test_no_filter_ok_when_step_has_content():
    text = ("Шаг 1. Фильтрация данных\n"
            "Учитываются записи в границах часа.\n"
            "Шаг 2. Обогащение данных\n")
    assert cf.check_no_filter(text, CFG) == []


def test_no_filter_ok_when_marked_na():
    text = "Шаг 1. Фильтрация данных\nне применимо\nШаг 2. Обогащение\n"
    assert cf.check_no_filter(text, CFG) == []


def test_no_filter_ignores_non_filter_empty_step():
    # пустой шаг НЕ про фильтрацию проверкой №4 не покрывается (фокус — фильтры)
    text = "Шаг 2. Обогащение данных\nШаг 3. Агрегация\n"
    assert cf.check_no_filter(text, CFG) == []


def test_no_filter_content_after_blank_line_not_fp():
    # содержание отделено пустой строкой — не должно считаться пустым шагом
    text = "Шаг 1. Фильтрация данных\n\nУчитываются записи в границах часа.\n\nШаг 2. Обогащение\n"
    assert cf.check_no_filter(text, CFG) == []


def test_no_filter_na_after_blank_line_not_fp():
    text = "Шаг 1. Фильтрация данных\n\nне применимо\nШаг 2. Обогащение\n"
    assert cf.check_no_filter(text, CFG) == []


def test_no_filter_second_filter_step_empty_flagged():
    # первый фильтровый шаг заполнен, второй — пустой: должен ловиться второй
    text = ("Шаг 1. Первичная фильтрация\nОтбор по периоду.\n"
            "Шаг 3. Вторичная фильтрация\nШаг 4. Агрегация\nГруппировка.\n")
    ids = [f["defect_id"] for f in cf.check_no_filter(text, CFG)]
    assert "NO_FILTER_DESCRIPTION" in ids


def test_data_catalog_flags_section_without_link():
    text = "Data Catalog\n\nИсходники проекта\nСсылка на GitLab: https://gitlab.corp/x\n"
    ids = [f["defect_id"] for f in cf.check_data_catalog(text, CFG)]
    assert "DATA_CATALOG_MISSING" in ids


def test_data_catalog_ok_when_link_present():
    text = ("Data Catalog\n"
            "Ссылка на Дата-каталог: https://datacatalog.corp/tables/x\n"
            "Исходники проекта\n")
    assert cf.check_data_catalog(text, CFG) == []


def test_data_catalog_ignores_when_section_absent():
    # раздела нет вовсе — это TEMPLATE_SECTION_MISSING, здесь не флагуем
    text = "Общие сведения\nНазвание витрины: X\nСхема: Y\n"
    assert cf.check_data_catalog(text, CFG) == []


def test_data_catalog_content_no_url_is_clarification_not_high():
    # реальный DOCX: URL — гиперлинк, теряется при конвертации; раздел не пустой.
    # R1: не давить ложным high в демо — мягкое clarification, дефект не скрыт.
    for body in ("Ссылка на Дата-каталог:",
                 "Каталог данных: см. Confluence",
                 "Дата-каталог в вики компании",
                 "Catalog owner: команда DWH"):
        text = f"Data Catalog\n{body}\nИсходники проекта\n"
        fs = cf.check_data_catalog(text, CFG)
        assert len(fs) == 1 and fs[0]["defect_id"] == "DATA_CATALOG_MISSING"
        assert fs[0]["severity"] == "clarification", f"ожидали clarification на: {body}"


def test_data_catalog_empty_section_is_high():
    # раздел есть, но пустой — ссылки точно нет, настоящий дефект high
    text = "Data Catalog\n\nИсходники проекта\n"
    fs = cf.check_data_catalog(text, CFG)
    assert len(fs) == 1 and fs[0]["defect_id"] == "DATA_CATALOG_MISSING"
    assert fs[0]["severity"] == "high"


def test_data_catalog_never_suppresses_defect():
    # ни один непустой/пустой раздел без URL не должен молча пройти (без ложных пропусков)
    for body in ("Ссылка на Дата-каталог не указана", "Прямая ссылка отсутствует",
                 "", "Catalog owner", "Дата-каталог: см. вики"):
        text = f"Data Catalog\n{body}\nИсходники проекта\n"
        ids = [f["defect_id"] for f in cf.check_data_catalog(text, CFG)]
        assert "DATA_CATALOG_MISSING" in ids, f"дефект пропущен на: {body!r}"


def test_data_catalog_link_in_other_section_does_not_count():
    # ссылка в СОСЕДНЕМ разделе не закрывает отсутствие ссылки в Data Catalog
    text = "Data Catalog\n\nИсходники проекта\nhttps://gitlab.corp/x\n"
    ids = [f["defect_id"] for f in cf.check_data_catalog(text, CFG)]
    assert "DATA_CATALOG_MISSING" in ids


_SRC = ("Источники данных\n"
        "Описание источника | Тип источника | Ссылка на источник | Сериализация\n")


def test_serialization_flags_empty_cell():
    text = _SRC + "Сырые события | Hive | SCHEMA.TABLE | —\nИсточники обогащения данных\n"
    ids = [f["defect_id"] for f in cf.check_serialization(text, CFG)]
    assert "SERIALIZATION_UNSPECIFIED" in ids


def test_serialization_ok_when_filled():
    text = _SRC + "Сырые события | Hive | SCHEMA.TABLE | ORC\nИсточники обогащения данных\n"
    assert cf.check_serialization(text, CFG) == []


def test_serialization_ignores_when_no_sources_section():
    text = "Общие сведения\nНазвание: X\n"
    assert cf.check_serialization(text, CFG) == []


def test_serialization_ignores_other_section_column():
    # «Сериализация» вне таблицы источников не проверяется
    text = ("Приемники данных\nОписание | Кластер | Сериализация\n"
            "Витрина | CLUSTER | —\n")
    assert cf.check_serialization(text, CFG) == []


def test_timezone_flags_local_time_value():
    text = "Часовой пояс: Местное время региона\n"
    ids = [f["defect_id"] for f in cf.check_timezone(text, CFG)]
    assert "TIMEZONE_UNDEFINED" in ids


def test_timezone_ok_when_utc():
    assert cf.check_timezone("Часовой пояс: UTC\n", CFG) == []


def test_timezone_ok_in_table_row():
    assert cf.check_timezone("Часовой пояс | UTC\n", CFG) == []


def test_timezone_ok_on_offset_and_iana():
    for value in ("UTC+3", "+03:00", "Europe/Moscow", "МСК"):
        assert cf.check_timezone("Часовой пояс: " + value + "\n", CFG) == [], value


def test_timezone_no_fp_on_source_field_description():
    # метка не в начале строки — это описание поля источника, а не поле «Часовой пояс»
    text = ("Коррекция часового пояса для временных меток:\n"
            "выполняется на стороне источника\n"
            "FIELD_TIME_ZONE_SHIFT | string | Сдвиг часового пояса\n")
    assert cf.check_timezone(text, CFG) == []


def test_timezone_value_on_next_line():
    assert cf.check_timezone("Часовой пояс:\nUTC\n", CFG) == []
    ids = [f["defect_id"] for f in
           cf.check_timezone("Часовой пояс:\nМестное время региона\n", CFG)]
    assert "TIMEZONE_UNDEFINED" in ids


def test_timezone_quote_is_verbatim():
    text = "Часовой пояс: Местное время региона\n"
    for f in cf.check_timezone(text, CFG):
        assert f["quote"] in text


def test_dangling_section_flags_missing_section():
    text = ("Алгоритм обработки потока\n"
            "Перечень мер приведён в разделе «Показатели витрины».\n")
    ids = [f["defect_id"] for f in cf.check_dangling_section(text, CFG)]
    assert "DANGLING_SECTION_REFERENCE" in ids


def test_dangling_section_ok_when_section_present():
    text = ("Структура данных\n"
            "Перечень мер приведён в разделе «Структура данных».\n")
    assert cf.check_dangling_section(text, CFG) == []


def test_dangling_section_ok_when_referenced_by_alias():
    # раздел присутствует под одним синонимом, ссылка зовёт его другим
    text = ("Общие сведения\n"
            "Состав описан в разделе «Общая информация».\n")
    assert cf.check_dangling_section(text, CFG) == []


def test_dangling_section_ignores_reference_without_name():
    # «см. выше» без имени раздела — не формальное правило, остаётся модели
    text = "Определяется по FIELD_OL_SERVICE_TYPE (см. выше).\nСм. раздел ниже.\n"
    assert cf.check_dangling_section(text, CFG) == []


def test_dangling_section_counts_table_cell_headings():
    # раздел объявлен первой ячейкой строки таблицы, а не отдельной строкой
    text = ("Часовой пояс | UTC\n"
            "Ссылка приведена в разделе «Часовой пояс».\n")
    assert cf.check_dangling_section(text, CFG) == []


def test_dangling_section_quote_is_verbatim():
    text = ("Алгоритм обработки потока\n"
            "Перечень мер приведён в разделе «Показатели витрины».\n")
    for f in cf.check_dangling_section(text, CFG):
        assert f["quote"] in text


def test_dangling_section_ignores_word_with_same_root():
    # блокеры кругов 1–2: однокоренные слова — не ссылка на раздел
    for text in ("Используйте разделитель «точка с запятой».\n",
                 "Описание дано в подразделе «Внешний алгоритм».\n",
                 "Разделка «туши» выполняется вручную.\n"):
        assert cf.check_dangling_section(text, CFG) == [], text


def test_dangling_section_all_case_forms_flagged():
    for text in ("Перечень приведён в разделе «Показатели витрины».\n",
                 "Данные описаны в разделах «Показатели витрины».\n",
                 "Содержание раздела «Показатели витрины» отсутствует.\n",
                 "Ссылка на раздел «Показатели витрины» ведёт в никуда.\n"):
        ids = [f["defect_id"] for f in cf.check_dangling_section(text, CFG)]
        assert "DANGLING_SECTION_REFERENCE" in ids, text


def test_dangling_section_ignores_external_link_line():
    # блокер круга 1: рядом URL — цель внешняя (EXTERNAL_LINKS_IN_CONFLUENCE)
    assert cf.check_dangling_section(
        "См. раздел «Внешний алгоритм» (https://confluence/x).\n", CFG) == []


def test_dangling_section_plural_form_still_flagged():
    ids = [f["defect_id"] for f in cf.check_dangling_section(
        "Данные описаны в разделах «Показатели витрины».\n", CFG)]
    assert "DANGLING_SECTION_REFERENCE" in ids


def test_negative_control_clean_docs_zero_fp():
    cleans = sorted(glob.glob("data/synth/synth_*_clean.txt"))
    assert cleans, "нет чистых документов"
    for path in cleans:
        text = open(path, encoding="utf-8").read()
        fs = cf.run(text, CFG)["findings"]
        assert fs == [], f"{path}: ожидали 0 FP, получили {[f['defect_id'] for f in fs]}"


if __name__ == "__main__":
    test_nullability_flags_receiver_row_without_marker()
    test_nullability_ok_when_marker_present()
    test_nullability_ignores_source_table()
    test_nullability_ignores_example_field_list()
    test_nullability_flags_when_column_removed_entirely()
    test_nullability_description_word_does_not_mask_empty_cell()
    test_nullability_marker_in_correct_cell_ok()
    test_hdfs_alternative_phrasings_without_format()
    test_hdfs_ignores_partition_section_header()
    test_hdfs_line_starting_with_other_alias_still_flagged()
    test_hdfs_partition_header_with_numbering_or_markdown_excluded()
    test_strip_numbering_variants()
    test_hdfs_flags_path_without_format()
    test_hdfs_ok_with_path_and_format()
    test_vague_wording_flags_loophole()
    test_vague_wording_flags_open_ended()
    test_vague_wording_quote_is_verbatim()
    test_vague_wording_all_configured_phrases_flagged()
    test_vague_wording_no_fp_on_negation_verb()
    test_vague_wording_spacing_variant()
    test_vague_wording_no_fp_on_technical_comparators()
    test_no_filter_flags_empty_filter_step()
    test_no_filter_ok_when_step_has_content()
    test_no_filter_ok_when_marked_na()
    test_no_filter_ignores_non_filter_empty_step()
    test_no_filter_content_after_blank_line_not_fp()
    test_no_filter_na_after_blank_line_not_fp()
    test_no_filter_second_filter_step_empty_flagged()
    test_data_catalog_flags_section_without_link()
    test_data_catalog_ok_when_link_present()
    test_data_catalog_ignores_when_section_absent()
    test_data_catalog_content_no_url_is_clarification_not_high()
    test_data_catalog_empty_section_is_high()
    test_data_catalog_never_suppresses_defect()
    test_serialization_flags_empty_cell()
    test_serialization_ok_when_filled()
    test_serialization_ignores_when_no_sources_section()
    test_serialization_ignores_other_section_column()
    test_data_catalog_link_in_other_section_does_not_count()
    test_timezone_flags_local_time_value()
    test_timezone_ok_when_utc()
    test_timezone_ok_in_table_row()
    test_timezone_ok_on_offset_and_iana()
    test_timezone_no_fp_on_source_field_description()
    test_timezone_value_on_next_line()
    test_timezone_quote_is_verbatim()
    test_dangling_section_flags_missing_section()
    test_dangling_section_ok_when_section_present()
    test_dangling_section_ok_when_referenced_by_alias()
    test_dangling_section_ignores_reference_without_name()
    test_dangling_section_counts_table_cell_headings()
    test_dangling_section_quote_is_verbatim()
    test_dangling_section_ignores_word_with_same_root()
    test_dangling_section_all_case_forms_flagged()
    test_dangling_section_ignores_external_link_line()
    test_dangling_section_plural_form_still_flagged()
    test_negative_control_clean_docs_zero_fp()
    print("все тесты пройдены")
