"""Deterministic success scenarios used by the Mock Analysis Core."""

from collections import Counter
from typing import Any

FindingSeed = tuple[str, str, str, str]

FINDING_SEEDS: tuple[FindingSeed, ...] = (
    (
        "MISSING_SELECTION_LOGIC",
        "high",
        "Логика отбора записей не описана.",
        "Укажите условия включения и исключения записей.",
    ),
    (
        "AMBIGUOUS_REQUIREMENT",
        "medium",
        "Данные должны загружаться регулярно.",
        "Укажите точное расписание или событие запуска.",
    ),
    (
        "SOURCE_UNDEFINED",
        "critical",
        "Значение берётся из основной системы.",
        "Укажите систему-источник, таблицу и поле.",
    ),
    (
        "FIELD_DESCRIPTION_INCOMPLETE",
        "low",
        "Поле содержит статус объекта.",
        "Перечислите допустимые значения статуса.",
    ),
    (
        "DATA_TYPE_MISMATCH",
        "high",
        "Дата события хранится в поле типа integer.",
        "Уточните формат даты и согласуйте тип поля.",
    ),
    (
        "UNIT_MISSING",
        "medium",
        "Период хранения: 30.",
        "Укажите единицу измерения периода хранения.",
    ),
    (
        "FILTER_LOGIC_MISSING",
        "critical",
        "В витрину попадают только актуальные записи.",
        "Опишите формальное условие определения актуальной записи.",
    ),
    (
        "TABLE_REFERENCE_INVALID",
        "low",
        "См. таблицу с описанием атрибутов ниже.",
        "Укажите точное имя или идентификатор таблицы.",
    ),
    (
        "EDGE_CASE_UNSPECIFIED",
        "medium",
        "При отсутствии значения используется значение по умолчанию.",
        "Укажите значение по умолчанию и условия его применения.",
    ),
    (
        "LOGIC_CONTRADICTION",
        "high",
        "Удалённые записи сохраняются и исключаются из хранения.",
        "Устраните противоречие в правилах обработки удалённых записей.",
    ),
    (
        "SECURITY_CONSTRAINT_MISSING",
        "critical",
        "Доступ к набору данных предоставляется пользователям.",
        "Укажите роли и правила предоставления доступа.",
    ),
    (
        "LOGGING_UNSPECIFIED",
        "low",
        "Ошибки загрузки фиксируются в журнале.",
        "Укажите состав события, уровень и место хранения журнала.",
    ),
    (
        "DUPLICATE_HANDLING_MISSING",
        "medium",
        "Повторные записи обрабатываются автоматически.",
        "Опишите ключ определения дубля и правило разрешения конфликта.",
    ),
    (
        "NULL_HANDLING_MISSING",
        "high",
        "Пустые значения допускаются для части атрибутов.",
        "Перечислите nullable-поля и правила их обработки.",
    ),
    (
        "TIMEZONE_UNDEFINED",
        "low",
        "Время события передаётся в локальном формате.",
        "Укажите часовой пояс и формат временной метки.",
    ),
    (
        "SLA_UNDEFINED",
        "medium",
        "Загрузка должна завершаться своевременно.",
        "Укажите допустимое время завершения загрузки.",
    ),
    (
        "OWNER_UNDEFINED",
        "high",
        "При ошибке необходимо уведомить ответственную команду.",
        "Укажите команду-владельца и канал уведомления.",
    ),
    (
        "PRECISION_UNDEFINED",
        "critical",
        "Сумма передаётся как десятичное значение.",
        "Укажите precision, scale и правило округления.",
    ),
    (
        "RETENTION_CONFLICT",
        "medium",
        "История хранится один год, архив удаляется через 400 дней.",
        "Согласуйте единый срок хранения и удаления данных.",
    ),
    (
        "ACCEPTANCE_CRITERIA_MISSING",
        "low",
        "Результат загрузки должен быть корректным.",
        "Добавьте измеримые критерии успешности загрузки.",
    ),
)


def _location(index: int) -> dict[str, Any]:
    section_path = [
        "Требования к витрине данных",
        "Функциональные требования",
        "Правила преобразования",
        f"Группа атрибутов {index // 5 + 1}",
        f"Атрибут {index + 1}",
    ]
    location: dict[str, Any] = {
        "page": index // 4 + 1,
        "section_path": section_path,
        "block_id": f"block-{index + 1:03d}",
    }
    if index % 2:
        location.update(
            {
                "table": "Атрибутный состав витрины",
                "row": index + 2,
                "column": "Описание / правило формирования",
            }
        )
    return location


def build_findings(count: int) -> list[dict[str, Any]]:
    """Build up to twenty stable findings with varied severities and locations."""

    if not 0 <= count <= len(FINDING_SEEDS):
        raise ValueError(f"finding count must be between 0 and {len(FINDING_SEEDS)}")

    findings: list[dict[str, Any]] = []
    for index, (defect_id, severity, quote, clarification) in enumerate(FINDING_SEEDS[:count]):
        findings.append(
            {
                "id": f"finding-{index + 1:03d}",
                "defect_id": defect_id,
                "severity": severity,
                "confidence": round(0.97 - index * 0.015, 3),
                "location": _location(index),
                "quote": quote,
                "problem": f"Формулировка не позволяет однозначно проверить требование: {quote}",
                "clarification": clarification,
                "detected_by": ["mock-rule", "mock-verifier"],
            }
        )
    return findings


def build_success_result(scenario: str, finding_count: int) -> dict[str, Any]:
    """Build one complete ReviewResult fixture."""

    findings = build_findings(finding_count)
    severity_counts = Counter(finding["severity"] for finding in findings)
    return {
        "schema_version": "1.0",
        "run_id": f"fixture-{scenario}",
        "status": "completed",
        "document": {
            "filename": f"{scenario}-требования.pdf",
            "document_type": "data-mart-requirements",
            "sha256": "a" * 64,
        },
        "engine": {"version": "0.1.0"},
        "review_pack": {"id": "mts-data-mart", "version": "mock-success-1.0"},
        "model": {"name": "mock", "prompt_versions": {"review": "fixture-1"}},
        "findings": findings,
        "summary": {
            "total_candidates": finding_count + 3 if finding_count else 0,
            "verified_candidates": finding_count + 1 if finding_count else 0,
            "returned_findings": finding_count,
            "critical": severity_counts["critical"],
            "high": severity_counts["high"],
            "medium": severity_counts["medium"],
            "low": severity_counts["low"],
        },
        "warnings": [],
        "timings": {"parse_ms": 40, "analysis_ms": 80, "total_ms": 120},
    }


def build_success_scenarios() -> dict[str, dict[str, Any]]:
    """Return all checked-in success scenarios keyed by filename."""

    return {
        "empty.json": build_success_result("empty", 0),
        "standard-12.json": build_success_result("standard-12", 12),
        "maximum-20.json": build_success_result("maximum-20", 20),
    }
