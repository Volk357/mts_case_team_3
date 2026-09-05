/*
  Человеческие названия типов дефектов. Источник — defects.yaml контура анализа;
  API отдаёт только идентификатор, а аналитику незачем читать NO_DEDUP_OR_KEY.
  При добавлении типа в таксономию строку сюда добавляет тот же коммит.
*/
export const DEFECT_TITLES: Record<string, string> = {
  AMBIGUOUS_LOGIC: "Неоднозначная формулировка логики",
  DANGLING_REFERENCE: "Ссылка на несуществующий объект",
  DANGLING_SECTION_REFERENCE: "Ссылка на отсутствующий раздел документа",
  DATA_CATALOG_MISSING: "Нет прямой ссылки на Дата-каталог",
  DUPLICATE_SEMANTICS: "Дублирование смысла между полями",
  FILTER_RESULT_UNDEFINED: "Не описана судьба отфильтрованных записей",
  HDFS_PATH_INCOMPLETE: "Путь HDFS без указания формата",
  INCOMPLETE_SCHEMA: "Структура данных описана не полностью",
  INTERNAL_CONTRADICTION: "Внутреннее противоречие",
  MISSING_SOURCE_LOCATION: "Не указано расположение источника или кластера",
  NO_DEDUP_OR_KEY: "Не задан ключ, гранулярность или правило дедупликации",
  NO_FILTER_DESCRIPTION: "Фильтрация не описана вовсе",
  NO_SCHEDULE: "Не указан регламент обновления",
  NO_VOLUME_ESTIMATE: "Не указан объём данных",
  NULLABILITY_UNSPECIFIED: "Не указан признак обязательности поля",
  PII_NO_PROTECTION: "Персональные данные без требований к защите",
  PLACEHOLDER_LEFT: "Незаполненный плейсхолдер",
  REFERENCE_LIST_MISSING: "Нет перечня используемых справочников",
  RETENTION_GAP: "Срок хранения указан не для всех слоёв",
  SCHEMA_INCONSISTENCY: "Несогласованность схем между объектами",
  SCHEMA_TYPE_MISMATCH: "Тип одноимённого поля различается между таблицами",
  SERIALIZATION_UNSPECIFIED: "Не указана модель сериализации потока",
  TEMPLATE_SECTION_MISSING: "Раздел шаблона удалён, а не помечен «не применимо»",
  TEXT_STRUCTURE_ERROR: "Ошибка изложения в алгоритме",
  TIMEZONE_INCONSISTENT: "Трактовка часового пояса расходится между разделами",
  TIMEZONE_UNDEFINED: "Часовой пояс не назван",
  UNDEFINED_EDGE_CASE: "Не описана обработка граничного случая",
  UNSPECIFIED_FORMAT: "Не задана единица измерения или перечень допустимых значений",
  VAGUE_WORDING: "Расплывчатая формулировка (лазейка / незакрытый перечень)",
};

export function defectTitle(defectId: string): string {
  return DEFECT_TITLES[defectId] ?? defectId;
}
