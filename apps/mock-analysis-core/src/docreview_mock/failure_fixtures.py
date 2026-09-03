"""Deterministic failure scenarios used by the Mock Analysis Core."""

from typing import Any


def _failed_result(
    run_id: str,
    code: str,
    stage: str,
    message: str,
    *,
    retriable: bool,
    schema_version: str = "1.0",
) -> dict[str, Any]:
    return {
        "schema_version": schema_version,
        "run_id": run_id,
        "status": "failed",
        "error": {
            "code": code,
            "stage": stage,
            "message": message,
            "retriable": retriable,
        },
    }


def build_failure_payloads() -> dict[str, dict[str, Any] | str]:
    """Return stdout fixtures keyed by their checked-in filename."""

    return {
        "document-parse-error.json": _failed_result(
            "fixture-document-parse-error",
            "DOCUMENT_PARSE_ERROR",
            "parsing",
            "Не удалось разобрать структуру документа.",
            retriable=False,
        ),
        "review-pack-not-found.json": _failed_result(
            "fixture-review-pack-not-found",
            "REVIEW_PACK_NOT_FOUND",
            "configuration",
            "Указанный Review Pack не найден.",
            retriable=False,
        ),
        "model-unavailable.json": _failed_result(
            "fixture-model-unavailable",
            "MODEL_UNAVAILABLE",
            "semantic_review",
            "Model endpoint is unavailable.",
            retriable=True,
        ),
        "analysis-timeout.json": _failed_result(
            "fixture-analysis-timeout",
            "ANALYSIS_TIMEOUT",
            "pipeline",
            "Превышено допустимое время анализа.",
            retriable=True,
        ),
        "incompatible-schema-version.json": _failed_result(
            "fixture-incompatible-schema-version",
            "INTERNAL_ERROR",
            "serialization",
            "Core returned a result using an unsupported contract version.",
            retriable=False,
            schema_version="2.0",
        ),
        "invalid-json.txt": '{"schema_version":"1.0","status":"failed","error":',
    }


def build_failure_manifest() -> dict[str, dict[str, Any]]:
    """Describe process behavior separately from stdout fixture contents."""

    return {
        "document-parse-error": {
            "exit_code": 3,
            "result_file": "document-parse-error.json",
            "stderr": "mock: document parsing failed",
            "delay_ms": 0,
        },
        "review-pack-not-found": {
            "exit_code": 4,
            "result_file": "review-pack-not-found.json",
            "stderr": "mock: review pack is unknown",
            "delay_ms": 0,
        },
        "model-unavailable": {
            "exit_code": 5,
            "result_file": "model-unavailable.json",
            "stderr": "mock: model endpoint is unavailable",
            "delay_ms": 0,
        },
        "invalid-json": {
            "exit_code": 6,
            "result_file": "invalid-json.txt",
            "stderr": "mock: model response is not valid JSON",
            "delay_ms": 0,
        },
        "incompatible-schema-version": {
            "exit_code": 0,
            "result_file": "incompatible-schema-version.json",
            "stderr": "mock: emitted unsupported schema version",
            "delay_ms": 0,
        },
        "timeout": {
            "exit_code": 8,
            "result_file": "analysis-timeout.json",
            "stderr": "mock: analysis timed out",
            "delay_ms": 1500,
        },
        "crash": {
            "exit_code": 7,
            "result_file": None,
            "stderr": "mock: unexpected pipeline crash",
            "delay_ms": 0,
        },
        "missing-result-after-success": {
            "exit_code": 0,
            "result_file": None,
            "stderr": "mock: completed without result",
            "delay_ms": 0,
        },
    }
