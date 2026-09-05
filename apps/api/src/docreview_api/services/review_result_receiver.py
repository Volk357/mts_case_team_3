"""Validate and atomically persist completed Analysis Core results."""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from jsonschema import Draft202012Validator
from sqlalchemy.orm import Session, sessionmaker

from docreview_api.db.models import ReviewJobModel
from docreview_api.models.review_result import prepare_review_result_snapshot
from docreview_api.repositories.database import ReviewJobRepository, complete_review_job
from docreview_api.services.process_runner import ProcessExecutionResult
from docreview_api.services.run_workspace import RunWorkspace

SCHEMA_VERSION_PATTERN = re.compile(r"^(?P<major>[0-9]+)\.(?P<minor>[0-9]+)$")


class ReviewResultAcceptanceError(ValueError):
    """Base error for an Analysis Core result rejected before persistence."""


class NonZeroProcessExitError(ReviewResultAcceptanceError):
    """A process that failed cannot publish a completed result."""


class ResultFileError(ReviewResultAcceptanceError):
    """The expected output is missing, unsafe, unreadable, or too large."""


class ResultEncodingError(ReviewResultAcceptanceError):
    """The result is not strict UTF-8."""


class ResultJsonError(ReviewResultAcceptanceError):
    """The UTF-8 result is not one JSON object."""


class ResultSchemaError(ReviewResultAcceptanceError):
    """The result violates the shared ReviewResult JSON Schema."""


class IncompatibleSchemaVersionError(ReviewResultAcceptanceError):
    """The result uses a schema major version unsupported by this application."""


class ResultIdentityMismatchError(ReviewResultAcceptanceError):
    """The result does not belong to the expected job/process."""


@dataclass(frozen=True, slots=True)
class _ExpectedJob:
    run_id: str
    process_pid: int | None
    document_sha256: str


class ReviewResultReceiver:
    """Treat CLI output as untrusted until every contract check has passed."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        schema_path: Path,
        max_result_size_bytes: int = 10 * 1024 * 1024,
        supported_schema_major: int = 1,
    ) -> None:
        if max_result_size_bytes < 1:
            raise ValueError("max_result_size_bytes must be positive")
        if supported_schema_major < 1:
            raise ValueError("supported_schema_major must be positive")
        try:
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(schema)
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("ReviewResult schema is unavailable or invalid") from error
        self._session_factory = session_factory
        self._validator = Draft202012Validator(schema)
        self._max_result_size_bytes = max_result_size_bytes
        self._supported_schema_major = supported_schema_major

    def receive(
        self,
        job_id: UUID,
        workspace: RunWorkspace,
        execution: ProcessExecutionResult,
    ) -> ReviewJobModel:
        """Validate one successful process output and commit it exactly once."""

        if execution.exit_code != 0:
            raise NonZeroProcessExitError(
                f"Analysis Core exited with non-zero code {execution.exit_code}"
            )
        expected = self._load_expected_job(job_id)
        if expected.run_id != workspace.run_id:
            raise ResultIdentityMismatchError("workspace run_id does not match review job")
        if expected.process_pid is not None and expected.process_pid != execution.pid:
            raise ResultIdentityMismatchError("process PID does not match review job")

        payload = self._read_payload(workspace)
        self._validate_schema_major(payload)
        errors = sorted(self._validator.iter_errors(payload), key=lambda error: list(error.path))
        if errors:
            error = errors[0]
            location = ".".join(str(part) for part in error.absolute_path) or "$"
            raise ResultSchemaError(f"ReviewResult schema validation failed at {location}")
        if payload.get("run_id") != expected.run_id:
            raise ResultIdentityMismatchError("result run_id does not match review job")
        if payload.get("status") != "completed":
            raise ResultSchemaError("exit code 0 requires a completed ReviewResult")
        self._validate_completed_invariants(payload)

        snapshot = prepare_review_result_snapshot(
            payload,
            expected_document_sha256=expected.document_sha256,
        )
        return complete_review_job(
            self._session_factory,
            job_id,
            snapshot,
            at=execution.finished_at,
        )

    def _load_expected_job(self, job_id: UUID) -> _ExpectedJob:
        with self._session_factory() as session:
            job = ReviewJobRepository(session).require(job_id)
            return _ExpectedJob(
                run_id=job.run_id,
                process_pid=job.process_pid,
                document_sha256=job.document.sha256,
            )

    def _read_payload(self, workspace: RunWorkspace) -> dict[str, Any]:
        result_path = workspace.resolve("output/result.json")
        if result_path.is_symlink() or not result_path.is_file():
            raise ResultFileError("Analysis Core result file is missing or unsafe")
        try:
            size = result_path.stat().st_size
            if size == 0 or size > self._max_result_size_bytes:
                raise ResultFileError("Analysis Core result file has an invalid size")
            content = result_path.read_bytes()
        except ResultFileError:
            raise
        except OSError as error:
            raise ResultFileError("Analysis Core result file cannot be read") from error
        if len(content) != size:
            raise ResultFileError("Analysis Core result file changed while it was read")
        try:
            text = content.decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise ResultEncodingError("Analysis Core result must use UTF-8") from error
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as error:
            raise ResultJsonError("Analysis Core result is not valid JSON") from error
        if not isinstance(payload, Mapping):
            raise ResultJsonError("Analysis Core result must be a JSON object")
        return cast(dict[str, Any], payload)

    def _validate_schema_major(self, payload: Mapping[str, Any]) -> None:
        version = payload.get("schema_version")
        if not isinstance(version, str):
            return
        match = SCHEMA_VERSION_PATTERN.fullmatch(version)
        if match is not None and int(match.group("major")) != self._supported_schema_major:
            raise IncompatibleSchemaVersionError(
                f"ReviewResult schema major {match.group('major')} is unsupported"
            )

    @staticmethod
    def _validate_completed_invariants(payload: Mapping[str, Any]) -> None:
        """Reject semantic contract violations without repairing core output."""

        findings = cast(list[dict[str, Any]], payload["findings"])
        summary = cast(dict[str, int], payload["summary"])
        finding_ids = [finding["id"] for finding in findings]
        duplicates = sorted(
            finding_id for finding_id, count in Counter(finding_ids).items() if count > 1
        )
        if duplicates:
            raise ResultSchemaError(
                f"ReviewResult finding IDs must be unique: {', '.join(duplicates)}"
            )

        returned = summary["returned_findings"]
        if returned != len(findings):
            raise ResultSchemaError(
                "ReviewResult summary.returned_findings does not match findings length"
            )

        severity_counts = Counter(finding["severity"] for finding in findings)
        for severity in ("critical", "high", "medium", "low"):
            if summary[severity] != severity_counts.get(severity, 0):
                raise ResultSchemaError(f"ReviewResult summary.{severity} does not match findings")

        if not returned <= summary["verified_candidates"] <= summary["total_candidates"]:
            raise ResultSchemaError("ReviewResult candidate counters are inconsistent")
