"""
Пять доменов витрин-агрегатов и сборка чистого документа
по единому шаблону кейсодателя «Потоковые данные/витрины».

Содержание доменов написано руками, а не моделью. Причина:
если базовый текст порождает та же модель, что потом его ревьюит,
измеренная полнота окажется завышенной. Детерминированный контент
снимает этот вопрос полностью и заодно делает генерацию
воспроизводимой.

Кейсодатель подтвердил 03.09.2026, что шаблон единый: алгоритм
расчёта витрины кладётся в раздел «Алгоритм обработки потока»,
партиционирование HDFS — в раздел «Формирование ключа (kafka) /
партиции (hdfs)».
"""

from model import Doc, para, line, kv, kvrow, table, row, steps, step

# Порядок разделов шаблона. Идентификаторы устойчивы, по ним работают мутаторы.
TEMPLATE_SECTIONS = [
    ("common", "Общие сведения"),
    ("problem", "Решаемая проблема"),
    ("metrics", "Продуктовые метрики"),
    ("customers", "Заказчики"),
    ("nfr", "Нефункциональные требования"),
    ("srcsystems", "Системы-источники"),
    ("catalog", "Data Catalog"),
    ("repo", "Исходники проекта"),
    ("team", "Команда"),
    ("jira", "JIRA"),
    ("sources", "Источники данных"),
    ("enrich", "Источники обогащения данных"),
    ("receivers", "Приемники данных"),
    ("scheme", "Схема потоков данных"),
    ("algo", "Алгоритм обработки потока"),
    ("key", "Формирование ключа (kafka) / партиции (hdfs)"),
    ("struct", "Структура данных"),
    ("sample", "Пример данных"),
    ("ddl", "DDL"),
    ("faq", "FAQ"),
    ("history", "История изменений"),
]


DOMAINS = {
    # ---------------------------------------------------------------
    "traffic": {
        "title": "Витрина-агрегат по интернет-трафику абонентов",
        "summary": "Агрегат по интернет-трафику: суточная сводка объёма переданных "
                   "данных в разрезе региона, технологии доступа и тарифного плана.",
        "problem": "Продуктовые команды считают потребление трафика вручную по "
                   "выгрузкам из RAW-слоя. Расчёты расходятся между командами, "
                   "воспроизвести цифру прошлого периода невозможно. Витрина "
                   "фиксирует единый способ расчёта.",
        "metrics": [
            "Время подготовки отчёта по потреблению: с 3 дней до 1 часа",
            "Доля расхождений между командами по объёму трафика: цель менее 1%",
        ],
        "customer": "BigData Unit X, продукт «Мобильный интернет»",
        "cluster": "KAFKA_CLUSTER_MSK_PROD",
        "schema": "SCHEMA_CDM_TRAFFIC",
        "target": "TABLE_AGG_TRAFFIC_DAILY",
        "hdfs": "/data/cdm/traffic/agg_traffic_daily",
        "hdfs_format": "ORC",
        "load_mode": "full_reload_period",
        "grain": "FIELD_BIZ_DATE, FIELD_REGION_CODE, FIELD_RAT, FIELD_TARIFF_CODE",
        "schedule": "Ежесуточно, в 03:00 UTC за предыдущие сутки",
        "depth": "С 01.01.2024",
        "volume": "Около 180 тыс. строк в суточной партиции, прирост около 40 МБ в сутки",
        "latency": "Готовность витрины не позднее 05:00 UTC",
        "timezone": "UTC",
        "retention": "RAW — 30 дней, DDS — 180 дней, CDM — 3 года",
        "src_system": "IUM — IN-платформа сбора событий интернет-трафика (GPRS/PS)",
        "topics": [
            ("TOPIC_IUM_PS_CENTRAL", "События PS-домена, Центр"),
            ("TOPIC_IUM_PS_URAL", "События PS-домена, Урал"),
        ],
        "sources": [
            ("Сырые события интернет-трафика", "Hive", "SCHEMA_RAW.TABLE_IUM_RAW_PS", "ORC"),
            ("Сессии PS-домена", "Hive", "SCHEMA_DDS.TABLE_PS_SESSION", "ORC"),
        ],
        "refs": [
            ("TABLE_REGION_REF", "SCHEMA_DIC", "Справочник регионов: код региона и наименование"),
            ("TABLE_TARIFF_REF", "SCHEMA_DIC", "Справочник тарифных планов, историчный по бизнес-дате"),
            ("TABLE_RAT_REF", "SCHEMA_DIC", "Справочник технологий радиодоступа: 2G, 3G, 4G, 5G"),
        ],
        "fields": [
            ("FIELD_BIZ_DATE", "date", "Бизнес-дата суток агрегации", "NOT NULL",
             "Партиция источника"),
            ("FIELD_REGION_CODE", "string", "Код региона абонента", "NOT NULL",
             "TABLE_REGION_REF.region_code"),
            ("FIELD_RAT", "string", "Технология радиодоступа: 2G, 3G, 4G, 5G", "NOT NULL",
             "TABLE_RAT_REF.rat_name"),
            ("FIELD_TARIFF_CODE", "string", "Код тарифного плана", "NULLABLE",
             "TABLE_TARIFF_REF.tariff_code"),
            ("FIELD_BYTES_UP", "bigint", "Объём переданных данных (байты)", "NOT NULL",
             "sum(TABLE_IUM_RAW_PS.bytes_up)"),
            ("FIELD_BYTES_DOWN", "bigint", "Объём принятых данных (байты)", "NOT NULL",
             "sum(TABLE_IUM_RAW_PS.bytes_down)"),
            ("FIELD_USERS_CNT", "bigint", "Уникальное количество абонентов (IMSI)", "NOT NULL",
             "count(distinct FIELD_IMSI)"),
            ("FIELD_PROC_TS", "timestamp", "Дата и время формирования агрегата", "NOT NULL",
             "Метка обработки DAG"),
        ],
        "src_fields": [
            ("FIELD_IMSI", "string", "Идентификатор абонента"),
            ("FIELD_SESSION_START", "timestamp", "Время начала сессии, UTC"),
            ("FIELD_SESSION_END", "timestamp", "Время окончания сессии, UTC"),
            ("FIELD_BYTES_UP", "bigint", "Переданные байты за сессию"),
            ("FIELD_BYTES_DOWN", "bigint", "Принятые байты за сессию"),
            ("FIELD_RAT_CODE", "int", "Код технологии радиодоступа"),
            ("FIELD_LAC", "int", "Код зоны локации"),
            ("FIELD_CELL_ID", "bigint", "Идентификатор соты"),
        ],
        "filter_rule": "Учитываются сессии, у которых FIELD_SESSION_START попадает "
                       "в границы бизнес-даты по UTC. Сессии, начавшиеся до 00:00 UTC "
                       "и завершившиеся после, относятся к дате начала.",
        "filter_fate": "Сессии с FIELD_BYTES_UP и FIELD_BYTES_DOWN равными нулю "
                       "отбрасываются и учитываются в счётчике отбраковки таблицы "
                       "TABLE_TRAFFIC_REJECT.",
        "enrich_desc": "Обогащение выполняется справочниками региона, тарифа и "
                       "технологии доступа по бизнес-дате расчёта.",
        "edge_case": "Если для абонента одновременно FIELD_LAC = 0 и FIELD_CELL_ID = 0, "
                     "региону присваивается значение Unknown.",
        "branch_lines": [
            "Приоритет сопоставления: пара (FIELD_LAC, FIELD_CELL_ID).",
            "Если FIELD_LAC = 0 — сопоставление только по FIELD_CELL_ID.",
            "Если FIELD_CELL_ID = 0 — сопоставление только по FIELD_LAC.",
        ],
        "faq": [
            "Почему объём считается в байтах, а не в мегабайтах: округление до "
            "мегабайт на суточной гранулярности даёт расхождение с биллингом.",
            "Абоненты без трафика в витрину не попадают: строка создаётся только "
            "при наличии хотя бы одной сессии.",
        ],
        "pii": "Поля FIELD_IMSI и FIELD_MSISDN в витрину не выгружаются. В слое RAW "
               "доступ к ним разграничен ролью ROLE_PII_READ, выгрузка вовне "
               "запрещена.",
        "history": "v1.0 от 12.02.2024 — первая редакция. v1.1 от 03.06.2024 — "
                   "добавлено поле FIELD_RAT.",
    },
    # ---------------------------------------------------------------
    "radio": {
        "title": "Витрина-агрегат по качеству радиосети",
        "summary": "Агрегат по качеству радиосети: часовая сводка показателей "
                   "доступности и удержания соединения в разрезе базовой станции.",
        "problem": "Показатели качества радиосети собираются в трёх системах "
                   "с разными формулами. Инженеры эксплуатации не могут сравнить "
                   "регионы между собой. Витрина сводит расчёт к одному определению.",
        "metrics": [
            "Время выявления деградации соты: с 6 часов до 1 часа",
            "Доля станций с полным набором показателей: цель выше 98%",
        ],
        "customer": "Технический блок, подразделение эксплуатации радиосети",
        "cluster": "KAFKA_CLUSTER_EKB_PROD",
        "schema": "SCHEMA_CDM_RADIO",
        "target": "TABLE_AGG_RADIO_HOURLY",
        "hdfs": "/data/cdm/radio/agg_radio_hourly",
        "hdfs_format": "Parquet",
        "load_mode": "upsert",
        "grain": "FIELD_BIZ_DATE, FIELD_HOUR, FIELD_CELL_ID",
        "schedule": "Ежечасно, на 15-й минуте следующего часа",
        "depth": "С 01.09.2024",
        "volume": "Около 2,4 млн строк в суточной партиции, прирост около 900 МБ в сутки",
        "latency": "Задержка от события до витрины не более 20 минут",
        "timezone": "UTC",
        "retention": "RAW — 14 дней, DDS — 90 дней, CDM — 1 год",
        "src_system": "PROVIDER_RAN — платформа сбора счётчиков с eNodeB и RNC",
        "topics": [
            ("TOPIC_RAN_COUNTERS_NW", "Счётчики радиосети, Северо-Запад"),
            ("TOPIC_RAN_COUNTERS_SIB", "Счётчики радиосети, Сибирь"),
        ],
        "sources": [
            ("Счётчики базовых станций", "Kafka", "TOPIC_RAN_COUNTERS_NW", "Avro"),
            ("Сырые счётчики радиосети", "Hive", "SCHEMA_RAW.TABLE_RAN_RAW_COUNTERS", "ORC"),
        ],
        "refs": [
            ("TABLE_BS_REF", "SCHEMA_ADDS", "Справочник базовых станций, историчный по бизнес-дате"),
            ("TABLE_REGION_REF", "SCHEMA_DIC", "Справочник регионов"),
            ("TABLE_VENDOR_REF", "SCHEMA_DIC", "Справочник вендоров оборудования"),
        ],
        "fields": [
            ("FIELD_BIZ_DATE", "date", "Бизнес-дата часа агрегации", "NOT NULL",
             "Партиция источника"),
            ("FIELD_HOUR", "int", "Час агрегации, 0–23", "NOT NULL",
             "Партиция источника"),
            ("FIELD_CELL_ID", "bigint", "Идентификатор соты", "NOT NULL",
             "TABLE_BS_REF.cell_id"),
            ("FIELD_VENDOR_NAME", "string", "Наименование вендора оборудования", "NULLABLE",
             "TABLE_VENDOR_REF.vendor_name"),
            ("FIELD_RRC_SUCCESS_RATE", "double", "Доля успешных установлений RRC (проценты)",
             "NOT NULL", "Расчёт по счётчикам RRC"),
            ("FIELD_DROP_CALL_RATE", "double", "Доля обрывов соединения (проценты)", "NOT NULL",
             "Расчёт по счётчикам обрывов"),
            ("FIELD_HANDOVER_CNT", "bigint", "Количество хэндоверов за час", "NOT NULL",
             "sum(TABLE_RAN_RAW_COUNTERS.ho_cnt)"),
            ("FIELD_PROC_TS", "timestamp", "Дата и время формирования агрегата", "NOT NULL",
             "Метка обработки DAG"),
        ],
        "src_fields": [
            ("FIELD_CELL_ID", "bigint", "Идентификатор соты"),
            ("FIELD_EVENT_TS", "timestamp", "Время снятия счётчика, UTC"),
            ("FIELD_RRC_ATTEMPT", "bigint", "Попытки установления RRC"),
            ("FIELD_RRC_SUCCESS", "bigint", "Успешные установления RRC"),
            ("FIELD_DROP_CNT", "bigint", "Количество обрывов"),
            ("FIELD_HO_CNT", "bigint", "Количество хэндоверов"),
            ("FIELD_CELL_GEN", "int", "Поколение сети: 3 или 4"),
        ],
        "filter_rule": "Учитываются счётчики, у которых FIELD_EVENT_TS попадает "
                       "в границы часа агрегации по UTC.",
        "filter_fate": "Счётчики с FIELD_RRC_ATTEMPT = 0 в расчёт долей не включаются "
                       "и записываются в таблицу отбраковки TABLE_RADIO_REJECT.",
        "enrich_desc": "Обогащение справочником базовых станций выполняется по "
                       "историческому срезу на бизнес-дату расчёта.",
        "edge_case": "Если сота отсутствует в TABLE_BS_REF на бизнес-дату расчёта, "
                     "вендору присваивается значение Unknown, строка сохраняется.",
        "branch_lines": [
            "Приоритет сопоставления: пара (FIELD_CELL_ID, FIELD_CELL_GEN).",
            "Если FIELD_CELL_GEN не заполнен — сопоставление только по FIELD_CELL_ID.",
            "Если сота присутствует в справочнике дважды, берётся запись "
            "с наибольшей датой начала действия.",
        ],
        "faq": [
            "Доли рассчитываются в процентах с двумя знаками после запятой, "
            "округление банковское.",
            "Часы без событий в витрину не попадают, пустые строки не создаются.",
        ],
        "pii": "Идентификаторы абонента в витрине отсутствуют. Данные обезличены "
               "на уровне источника, дополнительных требований к маскированию нет.",
        "history": "v1.0 от 20.09.2024 — первая редакция.",
    },
    # ---------------------------------------------------------------
    "churn": {
        "title": "Витрина-агрегат по оттоку абонентов",
        "summary": "Агрегат по оттоку: месячная сводка ушедших и оставшихся "
                   "абонентов в разрезе региона и причины расторжения.",
        "problem": "Расчёт оттока ведётся в презентациях подразделений, определение "
                   "ушедшего абонента отличается между регионами. Сравнение "
                   "динамики невозможно. Витрина закрепляет единое определение.",
        "metrics": [
            "Срок подготовки месячного отчёта по оттоку: с 5 дней до 1 суток",
            "Доля регионов с единым определением оттока: цель 100%",
        ],
        "customer": "Коммерческий блок, отдел удержания абонентов",
        "cluster": "KAFKA_CLUSTER_MSK_PROD",
        "schema": "SCHEMA_CDM_CHURN",
        "target": "TABLE_AGG_CHURN_MONTHLY",
        "hdfs": "/data/cdm/churn/agg_churn_monthly",
        "hdfs_format": "ORC",
        "load_mode": "full_reload_period",
        "grain": "FIELD_BIZ_DATE, FIELD_REGION_CODE, FIELD_CHURN_REASON",
        "schedule": "Ежемесячно, 1-го числа в 04:00 UTC за предыдущий месяц",
        "depth": "С 01.05.2023",
        "volume": "Около 5 тыс. строк в месячной партиции, прирост около 2 МБ в месяц",
        "latency": "Готовность витрины не позднее 3-го числа месяца",
        "timezone": "UTC",
        "retention": "RAW — 30 дней, DDS — 400 дней, CDM — 5 лет",
        "src_system": "CRM_CORE — система управления абонентской базой",
        "topics": [
            ("TOPIC_CRM_CONTRACT_EVENTS", "События изменения статуса договора"),
        ],
        "sources": [
            ("События изменения статуса договора", "Kafka", "TOPIC_CRM_CONTRACT_EVENTS", "JSON"),
            ("Витрина активных абонентов", "Hive", "SCHEMA_DDS.TABLE_SUBSCRIBER_STATE", "ORC"),
        ],
        "refs": [
            ("TABLE_REGION_REF", "SCHEMA_DIC", "Справочник регионов"),
            ("TABLE_CHURN_REASON_REF", "SCHEMA_DIC", "Справочник причин расторжения договора"),
        ],
        "fields": [
            ("FIELD_BIZ_DATE", "date", "Бизнес-дата: 1-е число месяца агрегации", "NOT NULL",
             "Период расчёта"),
            ("FIELD_REGION_CODE", "string", "Код региона абонента", "NOT NULL",
             "TABLE_REGION_REF.region_code"),
            ("FIELD_CHURN_REASON", "string", "Код причины расторжения", "NULLABLE",
             "TABLE_CHURN_REASON_REF.reason_code"),
            ("FIELD_CHURNED_CNT", "bigint", "Количество ушедших абонентов", "NOT NULL",
             "count(distinct FIELD_SUBSCRIBER_ID)"),
            ("FIELD_ACTIVE_CNT", "bigint", "Количество активных абонентов на начало месяца",
             "NOT NULL", "count по TABLE_SUBSCRIBER_STATE"),
            ("FIELD_CHURN_RATE", "double", "Доля оттока (проценты)", "NOT NULL",
             "FIELD_CHURNED_CNT / FIELD_ACTIVE_CNT * 100"),
            ("FIELD_PROC_TS", "timestamp", "Дата и время формирования агрегата", "NOT NULL",
             "Метка обработки DAG"),
        ],
        "src_fields": [
            ("FIELD_SUBSCRIBER_ID", "string", "Идентификатор абонента"),
            ("FIELD_CONTRACT_ID", "string", "Номер договора"),
            ("FIELD_STATUS_CODE", "string", "Код статуса договора"),
            ("FIELD_STATUS_TS", "timestamp", "Время изменения статуса, UTC"),
            ("FIELD_REASON_CODE", "string", "Код причины расторжения"),
            ("FIELD_REGION_CODE", "string", "Код региона обслуживания"),
        ],
        "filter_rule": "Ушедшим считается абонент, у которого FIELD_STATUS_CODE принял "
                       "значение CLOSED в границах месяца агрегации по UTC и не "
                       "вернулся в статус ACTIVE до конца месяца.",
        "filter_fate": "События с FIELD_STATUS_CODE вне справочника статусов "
                       "отбрасываются и логируются в TABLE_CHURN_REJECT.",
        "enrich_desc": "Обогащение справочником причин расторжения выполняется "
                       "по бизнес-дате расчёта.",
        "edge_case": "Если у абонента в течение месяца несколько переходов в CLOSED, "
                     "учитывается последний по FIELD_STATUS_TS.",
        "branch_lines": [
            "Приоритет определения региона: значение FIELD_REGION_CODE из события.",
            "Если FIELD_REGION_CODE в событии не заполнен — берётся регион "
            "из TABLE_SUBSCRIBER_STATE на начало месяца.",
            "Если регион не определён ни одним способом — присваивается Unknown.",
        ],
        "faq": [
            "Абонент, расторгнувший и заключивший договор в одном месяце, "
            "в отток не попадает.",
            "Доля оттока считается от активной базы на начало месяца, "
            "а не на конец.",
        ],
        "pii": "Поле FIELD_SUBSCRIBER_ID хешируется при выгрузке в CDM. "
               "Доступ к слою DDS разграничен ролью ROLE_PII_READ.",
        "history": "v1.0 от 15.06.2023 — первая редакция. v2.0 от 01.02.2024 — "
                   "изменено определение ушедшего абонента.",
    },
    # ---------------------------------------------------------------
    "roaming": {
        "title": "Витрина-агрегат по роумингу",
        "summary": "Агрегат по роумингу: суточная сводка событий абонентов "
                   "в сетях партнёров в разрезе страны и типа услуги.",
        "problem": "Сверка с роуминг-партнёрами занимает недели, расхождения "
                   "выявляются постфактум. Витрина даёт ежедневный срез "
                   "в терминах, сопоставимых с файлами TAP.",
        "metrics": [
            "Срок выявления расхождения с партнёром: с 30 до 2 суток",
            "Доля событий, сопоставленных с файлами TAP: цель выше 99%",
        ],
        "customer": "Финансовый блок, отдел межоператорских расчётов",
        "cluster": "KAFKA_CLUSTER_MSK_PROD",
        "schema": "SCHEMA_CDM_ROAMING",
        "target": "TABLE_AGG_ROAMING_DAILY",
        "hdfs": "/data/cdm/roaming/agg_roaming_daily",
        "hdfs_format": "ORC",
        "load_mode": "upsert",
        "grain": "FIELD_BIZ_DATE, FIELD_COUNTRY_CODE, FIELD_PARTNER_CODE, FIELD_SERVICE_TYPE",
        "schedule": "Ежесуточно, в 06:00 UTC за предыдущие сутки",
        "depth": "С 01.03.2024",
        "volume": "Около 60 тыс. строк в суточной партиции, прирост около 15 МБ в сутки",
        "latency": "Готовность витрины не позднее 08:00 UTC",
        "timezone": "UTC",
        "retention": "RAW — 90 дней, DDS — 400 дней, CDM — 7 лет",
        "src_system": "TAP_GATEWAY — шлюз обмена файлами TAP с роуминг-партнёрами",
        "topics": [
            ("TOPIC_ROAMING_EVENTS", "События роуминга, все направления"),
        ],
        "sources": [
            ("События роуминга исходящие", "Kafka", "TOPIC_ROAMING_EVENTS", "Avro"),
            ("Файлы TAP от партнёров", "SFTP", "/data/raw/roaming/tap_in", "TAP3, ASN.1"),
        ],
        "refs": [
            ("TABLE_COUNTRY_REF", "SCHEMA_DIC", "Справочник стран по коду MCC"),
            ("TABLE_PARTNER_REF", "SCHEMA_DIC", "Справочник роуминг-партнёров, историчный по бизнес-дате"),
            ("TABLE_SERVICE_REF", "SCHEMA_DIC", "Справочник типов услуг: голос, SMS, данные"),
        ],
        "fields": [
            ("FIELD_BIZ_DATE", "date", "Бизнес-дата суток агрегации", "NOT NULL",
             "Партиция источника"),
            ("FIELD_COUNTRY_CODE", "string", "Код страны пребывания", "NOT NULL",
             "TABLE_COUNTRY_REF.country_code"),
            ("FIELD_PARTNER_CODE", "string", "Код роуминг-партнёра", "NOT NULL",
             "TABLE_PARTNER_REF.partner_code"),
            ("FIELD_SERVICE_TYPE", "string", "Тип услуги: VOICE, SMS, DATA", "NOT NULL",
             "TABLE_SERVICE_REF.service_code"),
            ("FIELD_EVENT_CNT", "bigint", "Количество событий за сутки", "NOT NULL",
             "count(*)"),
            ("FIELD_DURATION_SEC", "bigint", "Суммарная длительность соединений (секунды)",
             "NULLABLE", "sum(FIELD_CALL_DURATION)"),
            ("FIELD_CHARGE_AMOUNT", "decimal(18,4)", "Начисленная сумма (валюта расчёта, SDR)",
             "NOT NULL", "sum(FIELD_CHARGE)"),
            ("FIELD_PROC_TS", "timestamp", "Дата и время формирования агрегата", "NOT NULL",
             "Метка обработки DAG"),
        ],
        "src_fields": [
            ("FIELD_IMSI", "string", "Идентификатор абонента"),
            ("FIELD_MCC", "string", "Мобильный код страны сети пребывания"),
            ("FIELD_MNC", "string", "Код сети оператора пребывания"),
            ("FIELD_EVENT_TS", "timestamp", "Время события в сети партнёра, UTC"),
            ("FIELD_CALL_DURATION", "int", "Длительность соединения (секунды)"),
            ("FIELD_CHARGE", "decimal(18,4)", "Сумма начисления по событию"),
            ("FIELD_SERVICE_CODE", "int", "Код типа услуги"),
        ],
        "filter_rule": "Учитываются события, у которых FIELD_EVENT_TS попадает "
                       "в границы бизнес-даты по UTC. События с датой старше 90 суток "
                       "в текущую партицию не принимаются.",
        "filter_fate": "События старше 90 суток помещаются в таблицу поздних "
                       "поступлений TABLE_ROAMING_LATE и обрабатываются отдельным "
                       "регламентом пересчёта.",
        "enrich_desc": "Обогащение справочником партнёров выполняется по историческому "
                       "срезу на бизнес-дату события, поскольку коды партнёров меняются.",
        "edge_case": "Если пара FIELD_MCC и FIELD_MNC отсутствует в справочнике партнёров, "
                     "партнёру присваивается значение Unknown, событие сохраняется "
                     "для последующей ручной разметки.",
        "branch_lines": [
            "Приоритет определения партнёра: пара (FIELD_MCC, FIELD_MNC).",
            "Если FIELD_MNC не заполнен — сопоставление только по FIELD_MCC "
            "с выбором партнёра по признаку основного оператора страны.",
            "Если FIELD_MCC не заполнен — событие направляется на ручную разметку.",
        ],
        "faq": [
            "Суммы приводятся к SDR по курсу на бизнес-дату события, "
            "а не на дату расчёта витрины.",
            "События, полученные повторно в файлах TAP, определяются по паре "
            "FIELD_IMSI и FIELD_EVENT_TS и не задваиваются.",
        ],
        "pii": "Поле FIELD_IMSI в витрину не выгружается. В слое RAW доступ "
               "разграничен ролью ROLE_PII_READ.",
        "history": "v1.0 от 10.03.2024 — первая редакция.",
    },
    # ---------------------------------------------------------------
    "services": {
        "title": "Витрина-агрегат по подключённым услугам",
        "summary": "Агрегат по услугам: месячная сводка подключений и отключений "
                   "дополнительных услуг в разрезе региона и категории услуги.",
        "problem": "Отчётность по подключениям собирается вручную из двух систем, "
                   "цифры расходятся с биллингом. Витрина даёт единый источник.",
        "metrics": [
            "Срок подготовки отчёта по подключениям: с 4 дней до 1 суток",
            "Расхождение с биллингом по количеству подключений: цель менее 0,5%",
        ],
        "customer": "Коммерческий блок, отдел дополнительных услуг",
        "cluster": "KAFKA_CLUSTER_MSK_PROD",
        "schema": "SCHEMA_CDM_SERVICES",
        "target": "TABLE_AGG_SERVICES_MONTHLY",
        "hdfs": "/data/cdm/services/agg_services_monthly",
        "hdfs_format": "ORC",
        "load_mode": "full_reload_period",
        "grain": "FIELD_BIZ_DATE, FIELD_REGION_CODE, FIELD_SERVICE_CATEGORY",
        "schedule": "Ежемесячно, 1-го числа в 05:00 UTC за предыдущий месяц",
        "depth": "С 01.01.2025",
        "volume": "Около 3 тыс. строк в месячной партиции, прирост около 1 МБ в месяц",
        "latency": "Готовность витрины не позднее 2-го числа месяца",
        "timezone": "UTC",
        "retention": "RAW — 30 дней, DDS — 400 дней, CDM — 3 года",
        "src_system": "PROV_SYS — система активации дополнительных услуг",
        "topics": [
            ("TOPIC_PROV_SERVICE_EVENTS", "События подключения и отключения услуг"),
        ],
        "sources": [
            ("События подключения услуг", "Kafka", "TOPIC_PROV_SERVICE_EVENTS", "JSON"),
            ("Сырые события активации", "Hive", "SCHEMA_RAW.TABLE_PROV_RAW_EVENTS", "ORC"),
        ],
        "refs": [
            ("TABLE_REGION_REF", "SCHEMA_DIC", "Справочник регионов"),
            ("TABLE_SERVICE_CATALOG_REF", "SCHEMA_DIC", "Каталог услуг с категориями, историчный по бизнес-дате"),
        ],
        "fields": [
            ("FIELD_BIZ_DATE", "date", "Бизнес-дата: 1-е число месяца агрегации", "NOT NULL",
             "Период расчёта"),
            ("FIELD_REGION_CODE", "string", "Код региона абонента", "NOT NULL",
             "TABLE_REGION_REF.region_code"),
            ("FIELD_SERVICE_CATEGORY", "string", "Категория услуги", "NOT NULL",
             "TABLE_SERVICE_CATALOG_REF.category_code"),
            ("FIELD_CONNECT_CNT", "bigint", "Количество подключений за месяц", "NOT NULL",
             "count по событиям ACTIVATE"),
            ("FIELD_DISCONNECT_CNT", "bigint", "Количество отключений за месяц", "NOT NULL",
             "count по событиям DEACTIVATE"),
            ("FIELD_NET_CNT", "bigint", "Чистый прирост подключений", "NOT NULL",
             "FIELD_CONNECT_CNT - FIELD_DISCONNECT_CNT"),
            ("FIELD_PROC_TS", "timestamp", "Дата и время формирования агрегата", "NOT NULL",
             "Метка обработки DAG"),
        ],
        "src_fields": [
            ("FIELD_SUBSCRIBER_ID", "string", "Идентификатор абонента"),
            ("FIELD_SERVICE_CODE", "string", "Код услуги"),
            ("FIELD_EVENT_TYPE", "string", "Тип события: ACTIVATE, DEACTIVATE"),
            ("FIELD_EVENT_TS", "timestamp", "Время события, UTC"),
            ("FIELD_REGION_CODE", "string", "Код региона обслуживания"),
            ("FIELD_CHANNEL_CODE", "string", "Код канала подключения"),
        ],
        "filter_rule": "Учитываются события, у которых FIELD_EVENT_TS попадает "
                       "в границы месяца агрегации по UTC.",
        "filter_fate": "События с FIELD_SERVICE_CODE, отсутствующим в каталоге услуг "
                       "на бизнес-дату, отбрасываются и логируются "
                       "в TABLE_SERVICES_REJECT.",
        "enrich_desc": "Обогащение каталогом услуг выполняется по историческому срезу "
                       "на бизнес-дату события, поскольку категории услуг "
                       "пересматриваются.",
        "edge_case": "Если услуга отсутствует в каталоге на бизнес-дату расчёта, "
                     "категории присваивается значение Unknown.",
        "branch_lines": [
            "Приоритет определения категории: код услуги на бизнес-дату события.",
            "Если на бизнес-дату записи нет — берётся ближайшая предшествующая "
            "запись каталога.",
            "Если предшествующих записей нет — категория Unknown.",
        ],
        "faq": [
            "Подключение и отключение одной услуги в одном месяце учитывается "
            "в обоих счётчиках.",
            "Чистый прирост может быть отрицательным, это ожидаемое поведение.",
        ],
        "pii": "Поле FIELD_SUBSCRIBER_ID в витрину не выгружается, агрегат "
               "не содержит идентификаторов абонента.",
        "history": "v1.0 от 20.01.2025 — первая редакция.",
    },
}


# Разделы, помечаемые «не применимо». Это норма, а не дефект:
# правило кейсодателя требует сохранять раздел с такой пометкой.
NA_SECTIONS = {
    "traffic": ["scheme", "history"],
    "radio": ["enrich", "sample", "history"],
    "churn": ["scheme", "sample"],
    "roaming": ["scheme", "history"],
    "services": ["scheme", "sample", "history"],
}


def build_clean(domain_key: str, doc_id: str) -> Doc:
    """Собирает чистый документ по шаблону. Дефектов нет по построению."""
    d = DOMAINS[domain_key]
    doc = Doc(doc_id, d["title"])
    na = set(NA_SECTIONS.get(domain_key, []))

    sec_nodes = {}
    for sid, title in TEMPLATE_SECTIONS:
        sec_nodes[sid] = doc.section(sid, title, na=(sid in na))

    def S(sid):
        return sec_nodes[sid]

    # --- Общие сведения
    S("common").add(para("common.summary", d["summary"]))
    b = S("common").add(kv("common.kv"))
    b.add(kvrow("common.table", "Название таблицы", f'{d["schema"]}.{d["target"]}'))
    b.add(kvrow("common.cluster", "Кластер", d["cluster"]))
    b.add(kvrow("common.schema", "Схема", d["schema"]))
    b.add(kvrow("common.load", "Способ загрузки",
                "Полная перезагрузка периода" if d["load_mode"] == "full_reload_period"
                else "Инкремент с обновлением по ключу (upsert)"))

    # --- Решаемая проблема
    S("problem").add(para("problem.text", d["problem"]))

    # --- Продуктовые метрики
    for i, m in enumerate(d["metrics"], 1):
        S("metrics").add(line(f"metrics.{i}", f"- {m}"))

    # --- Заказчики
    S("customers").add(para("customers.text", d["customer"]))

    # --- Нефункциональные требования
    b = S("nfr").add(kv("nfr.kv"))
    b.add(kvrow("nfr.volume", "Объём данных", d["volume"]))
    b.add(kvrow("nfr.latency", "Задержки", d["latency"]))
    b.add(kvrow("nfr.schedule", "Регламент расчёта", d["schedule"]))
    b.add(kvrow("nfr.depth", "Глубина данных", d["depth"]))
    b.add(kvrow("nfr.timezone", "Часовой пояс", d["timezone"]))
    b.add(kvrow("nfr.retention", "Срок хранения по слоям", d["retention"]))
    b.add(kvrow("nfr.update", "Обновление",
                "Полная перезагрузка периода без upsert"
                if d["load_mode"] == "full_reload_period"
                else "Обновление по ключу (upsert) в пределах партиции"))
    S("nfr").add(para("nfr.pii", d["pii"]))

    # --- Системы-источники
    S("srcsystems").add(para("srcsystems.text", d["src_system"]))

    # --- Data Catalog
    S("catalog").add(para(
        "catalog.link",
        f'Ссылка на Дата-каталог: '
        f'https://datacatalog.corp/tables/{d["schema"].lower()}.{d["target"].lower()}'))

    # --- Исходники проекта
    S("repo").add(para("repo.link",
                       f'Ссылка на GitLab: '
                       f'https://gitlab.corp/bigdata/{domain_key}-agg'))

    # --- Команда
    b = S("team").add(kv("team.kv"))
    b.add(kvrow("team.analyst", "Аналитик", "USER_A"))
    b.add(kvrow("team.dev", "Разработчик", "USER_B"))
    b.add(kvrow("team.qa", "Тестировщик", "USER_C"))

    # --- JIRA
    task = f"DATA-{4100 + len(domain_key)}"
    S("jira").add(para("jira.link",
                       f'Задача: {task} — {d["title"]}. '
                       f'https://jira.corp/browse/{task}'))

    # --- Источники данных
    t = S("sources").add(table(
        "sources.table",
        ["Описание источника", "Тип источника", "Ссылка на источник", "Сериализация"]))
    for i, (desc, typ, link, ser) in enumerate(d["sources"], 1):
        t.add(row(f"sources.row{i}", [desc, typ, link, ser]))

    # --- Источники обогащения данных (перечень НСИ, требование 8)
    if "enrich" not in na:
        S("enrich").add(para("enrich.text", d["enrich_desc"]))
        t = S("enrich").add(table(
            "enrich.table", ["Справочник", "Схема", "Назначение в расчёте"]))
        for i, (name, schema, desc) in enumerate(d["refs"], 1):
            t.add(row(f"enrich.row{i}", [name, schema, desc]))

    # --- Приемники данных
    t = S("receivers").add(table(
        "receivers.table",
        ["Описание данных", "Кластер", "Ссылка на Каталог", "Сериализация"]))
    t.add(row("receivers.row1",
              [d["title"], d["cluster"], f'{d["schema"]}.{d["target"]}', d["hdfs_format"]]))
    S("receivers").add(para(
        "receivers.hdfs",
        f'Путь хранения в HDFS: {d["hdfs"]}, формат {d["hdfs_format"]}.'))

    # --- Схема потоков данных
    if "scheme" not in na:
        S("scheme").add(para(
            "scheme.text",
            f'{d["src_system"].split(" — ")[0]} → Kafka ({d["cluster"]}) → '
            f'RAW → DDS → ADDS → CDM ({d["schema"]}.{d["target"]})'))

    # --- Алгоритм обработки потока
    st = S("algo").add(steps("algo.steps"))

    s1 = st.add(step("algo.s1", "Шаг 1. Фильтрация данных"))
    s1.add(line("algo.s1.rule", d["filter_rule"]))
    s1.add(line("algo.s1.fate", d["filter_fate"]))

    s2 = st.add(step("algo.s2", "Шаг 2. Обогащение данных"))
    s2.add(line("algo.s2.text",
                "Обогащение выполняется справочниками, перечисленными в разделе "
                "«Источники обогащения данных»."))
    for i, bl in enumerate(d["branch_lines"], 1):
        s2.add(line(f"algo.s2.branch{i}", bl))
    s2.add(line("algo.s2.edge", d["edge_case"]))

    s3 = st.add(step("algo.s3", "Шаг 3. Агрегация"))
    s3.add(line("algo.s3.group", f'Группировка по: {d["grain"]}.'))
    s3.add(line("algo.s3.calc",
                "Меры рассчитываются в границах группы, перечень мер приведён "
                "в разделе «Структура данных»."))

    s4 = st.add(step("algo.s4", "Шаг 4. Запись в CDM"))
    s4.add(line("algo.s4.text",
                f'Результат записывается в {d["schema"]}.{d["target"]} '
                f'в формате {d["hdfs_format"]} по пути {d["hdfs"]}.'))

    # --- Формирование ключа / партиции
    b = S("key").add(kv("key.kv"))
    b.add(kvrow("key.partition", "Поле партиционирования",
                d["grain"].split(",")[0].strip()))
    b.add(kvrow("key.grain", "Гранулярность строки", d["grain"]))
    b.add(kvrow("key.dedup", "Правило дедупликации",
                "Партиция перезаписывается целиком, дубли невозможны"
                if d["load_mode"] == "full_reload_period"
                else f'Ключ обновления: {d["grain"]}. При совпадении ключа '
                     f'сохраняется запись с большим FIELD_PROC_TS'))

    # --- Структура данных
    t = S("struct").add(table(
        "struct.recv",
        ["Атрибут", "Тип данных", "Описание атрибута", "Обязательность", "Источник"],
        caption=f'Приемники. Таблица: {d["schema"]}.{d["target"]}'))
    for f in d["fields"]:
        t.add(row(f"struct.recv.{f[0]}", list(f)))

    src_table = d["sources"][0][2].split(".")[-1]
    t = S("struct").add(table(
        "struct.src",
        ["Атрибут", "Тип данных", "Комментарий"],
        caption=f"Источники. Таблица: {src_table}"))
    for f in d["src_fields"]:
        t.add(row(f"struct.src.{f[0]}", list(f)))

    # --- Пример данных
    if "sample" not in na:
        t = S("sample").add(table(
            "sample.table", [f[0] for f in d["fields"]]))
        for i in range(1, 11):
            t.add(row(f"sample.row{i}", _sample_row(d, i)))

    # --- DDL
    S("ddl").add(para("ddl.text", _ddl(d)))

    # --- FAQ
    for i, q in enumerate(d["faq"], 1):
        S("faq").add(line(f"faq.{i}", f"- {q}"))

    # --- История изменений
    if "history" not in na:
        S("history").add(para("history.text", d["history"]))

    return doc


def _sample_row(d, i):
    """Строка примера данных, согласованная с типами полей."""
    out = []
    for name, typ, desc, _null, _src in d["fields"]:
        if typ == "date":
            out.append(f"2025-06-{i:02d}")
        elif typ == "timestamp":
            out.append(f"2025-06-{i:02d} 03:15:00")
        elif typ in ("bigint", "int"):
            out.append(str(1000 * i + 7))
        elif typ == "double":
            out.append(f"{90 + i * 0.37:.2f}")
        elif typ.startswith("decimal"):
            out.append(f"{120.5 * i:.4f}")
        elif "REGION" in name:
            out.append(f"REG_{i:02d}")
        elif "COUNTRY" in name:
            out.append(f"C{i:03d}")
        else:
            out.append(f"VAL_{i:02d}")
    return out


_TYPE_SQL = {"date": "DATE", "timestamp": "TIMESTAMP", "bigint": "BIGINT",
             "int": "INT", "double": "DOUBLE", "string": "STRING"}


def _ddl(d):
    cols = []
    for name, typ, _desc, null, _src in d["fields"]:
        sql = _TYPE_SQL.get(typ, typ.upper())
        cols.append(f"  {name} {sql}{'' if null == 'NULLABLE' else ' NOT NULL'}")
    part = d["grain"].split(",")[0].strip()
    return (f'CREATE TABLE {d["schema"]}.{d["target"]} (\n'
            + ",\n".join(cols)
            + f"\n)\nPARTITIONED BY ({part})\n"
            + f'STORED AS {d["hdfs_format"].upper()}\n'
            + f'LOCATION \'{d["hdfs"]}\';')
