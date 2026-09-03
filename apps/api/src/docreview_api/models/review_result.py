"""Lossless ReviewResult snapshot and normalized UI projection."""

import re
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Literal, cast

ReviewResultStatus = Literal["completed", "failed"]
_SHA256_PATTERN = re.compile(r"^[A-Fa-f0-9]{64}$")


class ReviewResultProjectionError(ValueError):
    """Raised when an already validated result cannot be safely projected."""


@dataclass(frozen=True)
class ReviewResultVersions:
    """Version snapshot needed to reproduce and explain a completed review."""

    schema_version: str
    core_version: str | None
    review_pack_id: str | None
    review_pack_version: str | None
    model_name: str | None
    prompt_versions: dict[str, str]


@dataclass(frozen=True)
class FindingProjection:
    """Queryable projection of one finding without changing its source values."""

    core_finding_id: str
    ordinal: int
    defect_id: str
    severity: str
    confidence: int | float
    location: dict[str, Any]
    quote: str
    problem: str
    clarification: str
    detected_by: tuple[str, ...]


@dataclass(frozen=True)
class ReviewResultSnapshot:
    """Raw result plus derived fields to persist in one transaction."""

    raw_result: dict[str, Any]
    run_id: str
    status: ReviewResultStatus
    document_sha256: str
    versions: ReviewResultVersions
    findings: tuple[FindingProjection, ...]


def _object(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReviewResultProjectionError(f"{field} must be an object")
    return cast(dict[str, Any], value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ReviewResultProjectionError(f"{field} must be a non-empty string")
    return value


def _project_findings(payload: dict[str, Any]) -> tuple[FindingProjection, ...]:
    source_findings = payload.get("findings")
    if not isinstance(source_findings, list):
        raise ReviewResultProjectionError("findings must be an array for a completed result")

    projections: list[FindingProjection] = []
    for ordinal, source in enumerate(source_findings):
        finding = _object(source, f"findings[{ordinal}]")
        confidence = finding.get("confidence")
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
            raise ReviewResultProjectionError(f"findings[{ordinal}].confidence must be a number")
        detected_by = finding.get("detected_by")
        if not isinstance(detected_by, list) or not all(
            isinstance(detector, str) for detector in detected_by
        ):
            raise ReviewResultProjectionError(
                f"findings[{ordinal}].detected_by must be a string array"
            )
        projections.append(
            FindingProjection(
                core_finding_id=_string(finding.get("id"), f"findings[{ordinal}].id"),
                ordinal=ordinal,
                defect_id=_string(finding.get("defect_id"), f"findings[{ordinal}].defect_id"),
                severity=_string(finding.get("severity"), f"findings[{ordinal}].severity"),
                confidence=confidence,
                location=deepcopy(
                    _object(finding.get("location"), f"findings[{ordinal}].location")
                ),
                quote=_string(finding.get("quote"), f"findings[{ordinal}].quote"),
                problem=_string(finding.get("problem"), f"findings[{ordinal}].problem"),
                clarification=_string(
                    finding.get("clarification"), f"findings[{ordinal}].clarification"
                ),
                detected_by=tuple(detected_by),
            )
        )
    return tuple(projections)


def prepare_review_result_snapshot(
    payload: Mapping[str, Any],
    *,
    expected_document_sha256: str,
) -> ReviewResultSnapshot:
    """Prepare an already contract-validated ReviewResult for atomic persistence.

    The caller remains responsible for JSON Schema validation and run_id matching.
    This function preserves the complete input object and derives query fields only.
    """

    if not _SHA256_PATTERN.fullmatch(expected_document_sha256):
        raise ReviewResultProjectionError("expected_document_sha256 must contain 64 hex digits")

    raw_result = deepcopy(dict(payload))
    schema_version = _string(raw_result.get("schema_version"), "schema_version")
    run_id = _string(raw_result.get("run_id"), "run_id")
    status_value = raw_result.get("status")
    if status_value not in {"completed", "failed"}:
        raise ReviewResultProjectionError("status must be completed or failed")
    status = cast(ReviewResultStatus, status_value)

    if status == "failed":
        versions = ReviewResultVersions(
            schema_version=schema_version,
            core_version=None,
            review_pack_id=None,
            review_pack_version=None,
            model_name=None,
            prompt_versions={},
        )
        findings: tuple[FindingProjection, ...] = ()
    else:
        document = _object(raw_result.get("document"), "document")
        result_sha256 = _string(document.get("sha256"), "document.sha256")
        if result_sha256.casefold() != expected_document_sha256.casefold():
            raise ReviewResultProjectionError("result document SHA-256 does not match Document")

        engine = _object(raw_result.get("engine"), "engine")
        review_pack = _object(raw_result.get("review_pack"), "review_pack")
        model = _object(raw_result.get("model"), "model")
        prompt_versions = _object(model.get("prompt_versions"), "model.prompt_versions")
        if not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in prompt_versions.items()
        ):
            raise ReviewResultProjectionError("model.prompt_versions must contain strings")
        versions = ReviewResultVersions(
            schema_version=schema_version,
            core_version=_string(engine.get("version"), "engine.version"),
            review_pack_id=_string(review_pack.get("id"), "review_pack.id"),
            review_pack_version=_string(review_pack.get("version"), "review_pack.version"),
            model_name=_string(model.get("name"), "model.name"),
            prompt_versions=deepcopy(prompt_versions),
        )
        findings = _project_findings(raw_result)

    return ReviewResultSnapshot(
        raw_result=raw_result,
        run_id=run_id,
        status=status,
        document_sha256=expected_document_sha256.lower(),
        versions=versions,
        findings=findings,
    )
