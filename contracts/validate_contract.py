"""Validation helpers for the ReviewResult integration contract."""

from __future__ import annotations

import json
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError


SCHEMA_PATH = Path(__file__).with_name("review-result.schema.json")


class ContractValidationError(ValueError):
    """Raised when a ReviewResult violates schema or cross-field invariants."""


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    with SCHEMA_PATH.open("r", encoding="utf-8") as schema_file:
        schema = json.load(schema_file)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def validate_review_result(payload: Mapping[str, Any]) -> None:
    """Validate a ReviewResult payload.

    JSON Schema covers shape and value ranges. This function additionally checks
    invariants that Draft 2020-12 cannot conveniently express.
    """

    errors = sorted(_validator().iter_errors(payload), key=lambda error: list(error.path))
    if errors:
        raise ContractValidationError(_format_schema_error(errors[0])) from errors[0]

    if payload["status"] != "completed":
        return

    findings = payload["findings"]
    summary = payload["summary"]
    finding_ids = [finding["id"] for finding in findings]
    duplicates = sorted(finding_id for finding_id, count in Counter(finding_ids).items() if count > 1)
    if duplicates:
        raise ContractValidationError(f"Finding IDs must be unique: {', '.join(duplicates)}")

    returned = summary["returned_findings"]
    if returned != len(findings):
        raise ContractValidationError(
            f"summary.returned_findings={returned} does not match findings length={len(findings)}"
        )

    severity_counts = Counter(finding["severity"] for finding in findings)
    for severity in ("critical", "high", "medium", "low"):
        expected = severity_counts.get(severity, 0)
        actual = summary[severity]
        if actual != expected:
            raise ContractValidationError(
                f"summary.{severity}={actual} does not match findings count={expected}"
            )

    verified = summary["verified_candidates"]
    total = summary["total_candidates"]
    if not returned <= verified <= total:
        raise ContractValidationError(
            "Candidate counters must satisfy returned_findings <= verified_candidates <= total_candidates"
        )


def _format_schema_error(error: ValidationError) -> str:
    path = ".".join(str(part) for part in error.absolute_path) or "$"
    return f"Contract validation failed at {path}: {error.message}"
