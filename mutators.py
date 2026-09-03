"""
Мутаторы: детерминированные функции порчи документа.

Версия 2. Главное изменение — классы дефектов.

Первый замер показал, что для дефектов удаления требование «процитируй
место дефекта» неисполнимо: удалённую строку процитировать нельзя, а
соседняя строка ничего об отсутствии не говорит. Инструмент указывал на
соседний раздел, на путь HDFS, на заголовок шага — все три ответа по
смыслу верны, а сопоставление по дословной цитате объявляло промахом
два из трёх.

Поэтому дефекты делятся на три класса, и каждый меряется своим правилом:

  presence         — испорченный текст в документе ЕСТЬ. Сопоставление
                     строгое, по дословной цитате.
  absence          — содержание вырезано, контейнер остался. Попадание,
                     если замечание указывает на любую строку того
                     раздела или шага, где содержание должно быть.
  section_removed  — раздел шаблона удалён целиком. Сопоставление
                     по имени раздела.

Контейнер для absence вычисляется автоматически: ближайший шаг или
раздел, содержавший удалённый узел.
"""

from model import row as make_row, line as make_line

DET = "deterministic"
LLM = "llm"

PRESENCE = "presence"
ABSENCE = "absence"
SECTION_REMOVED = "section_removed"


def apply_entry(doc, e: dict):
    op = e["op"]
    if op == "delete":
        doc.remove(e["target"])
    elif op == "delete_many":
        for t in e["targets"]:
            doc.remove(t)
    elif op == "set_text":
        doc.set_text(e["target"], e["text"])
    elif op == "set_cell":
        doc.set_cell(e["target"], e["col"], e["value"])
    elif op == "insert_line_after":
        doc.insert_after(e["target"], make_line(e["new_id"], e["text"]))
    elif op == "insert_row_after":
        doc.insert_after(e["target"], make_row(e["new_id"], e["cells"]))
    else:
        raise ValueError(f"неизвестная операция: {op}")


def targets_of(e: dict) -> list:
    return e.get("targets") or [e["target"]]


def _field_with_unit(d):
    for f in d["fields"]:
        if "(" in f[2]:
            return f
    return d["fields"][4]


def _strip_unit(text):
    return text.split("(")[0].strip()


def _shared_field(d):
    recv = {f[0]: f[1] for f in d["fields"]}
    for name, typ, _c in d["src_fields"]:
        if name in recv:
            return name, typ, recv[name]
    return None


# ---------------------------------------------------------------------
# presence: испорченный текст остаётся в документе
# ---------------------------------------------------------------------

def r_dangling_reference(d):
    return dict(
        defect_id="DANGLING_REFERENCE", defect_class=PRESENCE,
        op="set_text", target="algo.s3.calc", anchor="algo.s3.calc",
        mutation="reference_to_missing_section", detectable_by=LLM,
        text="Меры рассчитываются в границах группы, перечень мер приведён "
             "в разделе «Показатели витрины».",
        note="Ссылка на раздел «Показатели витрины», которого в документе "
             "нет. Исходно ссылка вела на раздел «Структура данных».")


def r_internal_contradiction(d):
    full = d["load_mode"] == "full_reload_period"
    text = ("Загрузка выполняется инкрементально, ранее записанные строки "
            "обновляются по ключу."
            if full else
            "Партиция периода перезаписывается целиком, обновление по ключу "
            "не выполняется.")
    return dict(
        defect_id="INTERNAL_CONTRADICTION", defect_class=PRESENCE,
        op="insert_line_after", target="common.load",
        new_id="mut.contradiction", anchor="mut.contradiction",
        mutation="insert_contradicting_statement", detectable_by=LLM,
        text=text,
        note="Вставленное утверждение противоречит строке «Обновление» "
             "в нефункциональных требованиях. Обе стороны в тексте дословно.")


def r_ambiguous_logic(d):
    return dict(
        defect_id="AMBIGUOUS_LOGIC", defect_class=PRESENCE,
        op="set_text", target="algo.s2.branch1", anchor="algo.s2.branch1",
        mutation="removed_priority_order", detectable_by=LLM,
        text="Сопоставление выполняется по имеющимся полям.",
        note="Из правила убран явный приоритет применения. Частные случаи "
             "остались, порядок их применения не определён.")


def r_unspecified_format(d):
    f = _field_with_unit(d)
    return dict(
        defect_id="UNSPECIFIED_FORMAT", defect_class=PRESENCE,
        op="set_cell", target="struct.recv." + f[0], col=2,
        value=_strip_unit(f[2]), anchor="struct.recv." + f[0],
        mutation="removed_unit_of_measure", detectable_by=LLM,
        note="У поля " + f[0] + " убрана единица измерения из описания. "
             "Тип данных остался, величина без единицы неоднозначна.")


def r_duplicate_semantics(d):
    uf = _field_with_unit(d)[0]
    numeric = [f for f in d["fields"]
               if (f[1] in ("bigint", "int", "double")
                   or f[1].startswith("decimal")) and f[0] != uf]
    base = numeric[0] if numeric else d["fields"][5]
    new_name = base[0] + "_TOTAL"
    return dict(
        defect_id="DUPLICATE_SEMANTICS", defect_class=PRESENCE,
        op="insert_row_after", target="struct.recv." + base[0],
        new_id="struct.recv." + new_name,
        cells=[new_name, base[1], base[2], base[3], base[4]],
        anchor="struct.recv." + new_name,
        mutation="insert_near_duplicate_field", detectable_by=LLM,
        note="Добавлено поле " + new_name + " с описанием, неотличимым "
             "от " + base[0] + ". Разница между полями не объяснена.")


def r_schema_inconsistency(d):
    sh = _shared_field(d)
    if sh is None:
        return None
    name, src_type, recv_type = sh
    new_type = "string" if src_type != "string" else "bigint"
    return dict(
        defect_id="SCHEMA_INCONSISTENCY", defect_class=PRESENCE,
        op="set_cell", target="struct.src." + name, col=1, value=new_type,
        anchor="struct.src." + name,
        mutation="changed_type_of_shared_field", detectable_by=LLM,
        note="Поле " + name + " описано в источнике как " + new_type +
             ", а в витрине как " + recv_type + ". Расхождение не объяснено.")


def r_missing_source_location(d):
    return dict(
        defect_id="MISSING_SOURCE_LOCATION", defect_class=PRESENCE,
        op="set_cell", target="receivers.row1", col=1, value="—",
        anchor="receivers.row1", mutation="cleared_cluster_cell",
        detectable_by=LLM,
        note="В таблице приёмников очищена колонка «Кластер». Подключиться "
             "к приёмнику без указания кластера нельзя.")


def r_placeholder_left(d):
    return dict(
        defect_id="PLACEHOLDER_LEFT", defect_class=PRESENCE,
        op="set_text", target="common.cluster", anchor="common.cluster",
        mutation="value_replaced_by_placeholder", detectable_by=DET,
        text="CLUSTER",
        note="Вместо имени кластера осталась заглушка CLUSTER. Соглашения "
             "TABLE_*, FIELD_*, SCHEMA_* заглушками не являются.")


def r_placeholder_left_jira(d):
    return dict(
        defect_id="PLACEHOLDER_LEFT", defect_class=PRESENCE,
        op="set_text", target="jira.link", anchor="jira.link",
        mutation="task_number_replaced_by_placeholder", detectable_by=DET,
        text="Задача: PROJECT-XX — " + d["title"] + ". LINK_JIRA_TASK",
        note="Вместо номера задачи осталась заглушка PROJECT-XX, вместо "
             "ссылки — LINK_JIRA_TASK.")


def r_no_schedule(d):
    short = ("Ежемесячно" if "Ежемесячно" in d["schedule"] else
             "Ежесуточно" if "Ежесуточно" in d["schedule"] else "Ежечасно")
    return dict(
        defect_id="NO_SCHEDULE", defect_class=PRESENCE,
        op="set_text", target="nfr.schedule", anchor="nfr.schedule",
        mutation="removed_run_time", detectable_by=LLM, text=short,
        note="Частота осталась, число и время запуска удалены. Кейсодатель "
             "отнёс такой случай к категории «требующий уточнения».")


def r_retention_gap(d):
    first = d["retention"].split(",")[0].strip()
    return dict(
        defect_id="RETENTION_GAP", defect_class=PRESENCE,
        op="set_text", target="nfr.retention", anchor="nfr.retention",
        mutation="removed_retention_for_layers", detectable_by=LLM,
        text=first,
        note="Срок хранения оставлен только для одного слоя. Для остальных "
             "слоёв, перечисленных в схеме потоков, срок не указан.")


def r_timezone_undefined(d):
    return dict(
        defect_id="TIMEZONE_UNDEFINED", defect_class=PRESENCE,
        op="set_text", target="nfr.timezone", anchor="nfr.timezone",
        mutation="timezone_replaced_by_local", detectable_by=LLM,
        text="Местное время региона",
        note="Часовой пояс требований изменён на местное время, при этом "
             "правило фильтрации в шаге 1 определяет границы периода по UTC. "
             "Поле с меткой смещения не названо.")


def r_text_structure_error(d):
    measure = d["fields"][-2][0]
    return dict(
        defect_id="TEXT_STRUCTURE_ERROR", defect_class=PRESENCE,
        op="set_text", target="algo.s3.group", anchor="algo.s3.group",
        mutation="aggregate_added_to_group_by", detectable_by=LLM,
        text="Группировка по: " + d["grain"] + ", " + measure + ".",
        note="В список группировки добавлено поле " + measure +
             ", которое является мерой, а не измерением.")


def r_serialization_unspecified(d):
    return dict(
        defect_id="SERIALIZATION_UNSPECIFIED", defect_class=PRESENCE,
        op="set_cell", target="sources.row1", col=3, value="—",
        anchor="sources.row1", mutation="cleared_serialization_cell",
        detectable_by=LLM,
        note="Для источника не указана сериализация: ни формат, ни схема, "
             "ни способ десериализации. Требование кейсодателя №1.")


def r_hdfs_path_incomplete(d):
    return dict(
        defect_id="HDFS_PATH_INCOMPLETE", defect_class=PRESENCE,
        op="set_text", target="receivers.hdfs", anchor="receivers.hdfs",
        mutation="path_replaced_by_folder_stub", detectable_by=DET,
        text="Путь хранения в HDFS: Папка.",
        note="Полный путь и формат хранения заменены заглушкой «Папка». "
             "Требование кейсодателя №7.")


def r_nullability_unspecified(d):
    f = d["fields"][3]
    return dict(
        defect_id="NULLABILITY_UNSPECIFIED", defect_class=PRESENCE,
        op="set_cell", target="struct.recv." + f[0], col=3, value="—",
        anchor="struct.recv." + f[0], mutation="cleared_nullability_cell",
        detectable_by=DET,
        note="У поля " + f[0] + " снят признак обязательности. "
             "Требование кейсодателя №3.")


# ---------------------------------------------------------------------
# absence: содержание вырезано, контейнер остался
# ---------------------------------------------------------------------

def r_incomplete_schema(d):
    return dict(
        defect_id="INCOMPLETE_SCHEMA", defect_class=ABSENCE,
        op="delete", target="struct.recv", extra_containers=["receivers"],
        mutation="removed_receiver_field_table", detectable_by=LLM,
        note="Таблица витрины объявлена в разделе «Приемники данных», но "
             "перечень её полей удалён из раздела «Структура данных». "
             "Ссылки на внешнее описание нет.")


def r_undefined_edge_case(d):
    return dict(
        defect_id="UNDEFINED_EDGE_CASE", defect_class=ABSENCE,
        op="delete", target="algo.s2.edge",
        mutation="removed_edge_case_rule", detectable_by=LLM,
        note="Удалено правило, закрывавшее граничный случай алгоритма "
             "обогащения. Соседние правила ветвления сохранены.")


def r_filter_result_undefined(d):
    return dict(
        defect_id="FILTER_RESULT_UNDEFINED", defect_class=ABSENCE,
        op="delete", target="algo.s1.fate",
        mutation="removed_rejected_records_fate", detectable_by=LLM,
        note="Правило фильтрации сохранено, описание судьбы отсеянных "
             "записей удалено.")


def r_no_filter_description(d):
    return dict(
        defect_id="NO_FILTER_DESCRIPTION", defect_class=ABSENCE,
        op="delete_many", targets=["algo.s1.rule", "algo.s1.fate"],
        mutation="emptied_filter_step", detectable_by=DET,
        note="Шаг фильтрации объявлен заголовком, но содержания не имеет.")


def r_no_dedup_or_key(d):
    return dict(
        defect_id="NO_DEDUP_OR_KEY", defect_class=ABSENCE,
        op="delete", target="key.dedup",
        mutation="removed_dedup_rule", detectable_by=LLM,
        note="Документ заявляет обновление по ключу (upsert), но правило "
             "разрешения дублей удалено. Для витрин с полной перезагрузкой "
             "периода это дефектом не является, здесь режим другой.")


def r_no_volume_estimate(d):
    return dict(
        defect_id="NO_VOLUME_ESTIMATE", defect_class=ABSENCE,
        op="delete", target="nfr.volume",
        mutation="removed_volume_row", detectable_by=LLM,
        note="Из нефункциональных требований удалена оценка объёма данных. "
             "Соседние требования сохранены.")


def r_pii_no_protection(d):
    return dict(
        defect_id="PII_NO_PROTECTION", defect_class=ABSENCE,
        op="delete", target="nfr.pii", extra_containers=["struct"],
        mutation="removed_pii_requirements", detectable_by=LLM,
        note="Требования к защите идентификаторов абонента удалены, "
             "идентификатор остался в структуре источника.")


def r_reference_list_missing(d):
    return dict(
        defect_id="REFERENCE_LIST_MISSING", defect_class=ABSENCE,
        op="delete", target="enrich.table",
        mutation="removed_reference_catalog_table", detectable_by=LLM,
        note="Удалён перечень справочников с назначением каждого. Сами "
             "справочники используются в алгоритме. Требование №8.")


def r_data_catalog_missing(d):
    return dict(
        defect_id="DATA_CATALOG_MISSING", defect_class=ABSENCE,
        op="delete", target="catalog.link",
        mutation="removed_datacatalog_link", detectable_by=DET,
        note="Раздел Data Catalog остался, ссылка из него удалена. "
             "Требование №2 обязывает давать прямую ссылку.")


# ---------------------------------------------------------------------
# section_removed: раздел шаблона удалён целиком
# ---------------------------------------------------------------------

def r_template_section_missing_faq(d):
    return dict(
        defect_id="TEMPLATE_SECTION_MISSING", defect_class=SECTION_REMOVED,
        op="delete", target="faq", anchor="ddl.text",
        mutation="removed_template_section", detectable_by=DET,
        note="Раздел FAQ удалён, а не помечен «не применимо». Правило №5 "
             "требует сохранять все разделы шаблона.")


def r_template_section_missing_ddl(d):
    return dict(
        defect_id="TEMPLATE_SECTION_MISSING", defect_class=SECTION_REMOVED,
        op="delete", target="ddl", anchor="faq.1",
        mutation="removed_template_section", detectable_by=DET,
        note="Раздел DDL удалён, а не помечен «не применимо». Правило №5 "
             "требует сохранять все разделы шаблона.")


RECIPES = {
    "DANGLING_REFERENCE": r_dangling_reference,
    "INTERNAL_CONTRADICTION": r_internal_contradiction,
    "INCOMPLETE_SCHEMA": r_incomplete_schema,
    "UNDEFINED_EDGE_CASE": r_undefined_edge_case,
    "AMBIGUOUS_LOGIC": r_ambiguous_logic,
    "UNSPECIFIED_FORMAT": r_unspecified_format,
    "DUPLICATE_SEMANTICS": r_duplicate_semantics,
    "SCHEMA_INCONSISTENCY": r_schema_inconsistency,
    "MISSING_SOURCE_LOCATION": r_missing_source_location,
    "PLACEHOLDER_LEFT": r_placeholder_left,
    "PLACEHOLDER_LEFT_JIRA": r_placeholder_left_jira,
    "FILTER_RESULT_UNDEFINED": r_filter_result_undefined,
    "NO_FILTER_DESCRIPTION": r_no_filter_description,
    "NO_DEDUP_OR_KEY": r_no_dedup_or_key,
    "NO_VOLUME_ESTIMATE": r_no_volume_estimate,
    "NO_SCHEDULE": r_no_schedule,
    "RETENTION_GAP": r_retention_gap,
    "TIMEZONE_UNDEFINED": r_timezone_undefined,
    "PII_NO_PROTECTION": r_pii_no_protection,
    "TEXT_STRUCTURE_ERROR": r_text_structure_error,
    "SERIALIZATION_UNSPECIFIED": r_serialization_unspecified,
    "REFERENCE_LIST_MISSING": r_reference_list_missing,
    "TEMPLATE_SECTION_MISSING_FAQ": r_template_section_missing_faq,
    "TEMPLATE_SECTION_MISSING_DDL": r_template_section_missing_ddl,
    "NULLABILITY_UNSPECIFIED": r_nullability_unspecified,
    "DATA_CATALOG_MISSING": r_data_catalog_missing,
    "HDFS_PATH_INCOMPLETE": r_hdfs_path_incomplete,
}
