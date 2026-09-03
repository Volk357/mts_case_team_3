"""Safe mapping and persistence of Analysis Core process failures."""

# ruff: noqa: RUF001

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from docreview_api.db.models import ReviewJobModel
from docreview_api.models.review_job_state import ReviewJobFailure
from docreview_api.repositories.database import ReviewJobRepository
from docreview_api.services.process_runner import ProcessExecutionResult
from docreview_api.services.review_result_receiver import (
    IncompatibleSchemaVersionError,
    ResultIdentityMismatchError,
    ReviewResultAcceptanceError,
)
from docreview_api.services.run_workspace import RunWorkspace

MAX_FAILURE_RESULT_BYTES = 64 * 1024
DEFAULT_DIAGNOSTIC_LIMIT = 4096
_WHITESPACE_PATTERN = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class ErrorDescriptor:
    user_message: str
    retriable: bool
    exit_codes: frozenset[int]


ERROR_CATALOG: dict[str, ErrorDescriptor] = {
    "INVALID_ARGUMENTS": ErrorDescriptor(
        "Не удалось запустить проверку из-за некорректной конфигурации.", False, frozenset({2})
    ),
    "DOCUMENT_READ_ERROR": ErrorDescriptor("Не удалось прочитать документ.", False, frozenset({3})),
    "DOCUMENT_PARSE_ERROR": ErrorDescriptor(
        "Не удалось разобрать структуру документа.", False, frozenset({3})
    ),
    "UNSUPPORTED_DOCUMENT": ErrorDescriptor(
        "Формат документа не поддерживается.", False, frozenset({3})
    ),
    "REVIEW_PACK_NOT_FOUND": ErrorDescriptor(
        "Выбранный пакет проверки не найден.", False, frozenset({4})
    ),
    "REVIEW_PACK_INVALID": ErrorDescriptor(
        "Выбранный пакет проверки некорректен.", False, frozenset({4})
    ),
    "REVIEW_PACK_INCOMPATIBLE": ErrorDescriptor(
        "Пакет проверки несовместим с текущей версией системы.", False, frozenset({4})
    ),
    "MODEL_UNAVAILABLE": ErrorDescriptor(
        "Модель временно недоступна. Попробуйте повторить проверку.", True, frozenset({5})
    ),
    "MODEL_TIMEOUT": ErrorDescriptor(
        "Модель не ответила вовремя. Попробуйте повторить проверку.", True, frozenset({5})
    ),
    "MODEL_AUTH_FAILED": ErrorDescriptor(
        "Не удалось авторизоваться в сервисе модели.", False, frozenset({5})
    ),
    "MODEL_CONFIG_INVALID": ErrorDescriptor(
        "Конфигурация модели некорректна.", False, frozenset({5})
    ),
    "MODEL_RESPONSE_INVALID": ErrorDescriptor(
        "Модель вернула некорректный результат. Проверку можно повторить.",
        True,
        frozenset({6}),
    ),
    "INTERNAL_ERROR": ErrorDescriptor(
        "Во время проверки произошла внутренняя ошибка.", False, frozenset({7})
    ),
    "ANALYSIS_TIMEOUT": ErrorDescriptor(
        "Проверка превысила допустимое время выполнения.", True, frozenset({8})
    ),
    "ANALYSIS_CANCELLED": ErrorDescriptor("Проверка отменена.", False, frozenset({8})),
    "CORE_PROCESS_FAILED": ErrorDescriptor(
        "Процесс проверки завершился с ошибкой.", False, frozenset()
    ),
    "CORE_RESULT_INVALID": ErrorDescriptor(
        "Результат проверки имеет некорректный формат.", False, frozenset()
    ),
    "CORE_SCHEMA_INCOMPATIBLE": ErrorDescriptor(
        "Версия результата проверки не поддерживается.", False, frozenset()
    ),
    "CORE_RESULT_MISMATCH": ErrorDescriptor(
        "Получен результат от другого запуска проверки.", False, frozenset()
    ),
    "WORKER_INTERRUPTED": ErrorDescriptor(
        "Проверка была прервана. Запустите её повторно.", True, frozenset()
    ),
    "WORKER_EXECUTION_ERROR": ErrorDescriptor("Не удалось выполнить проверку.", False, frozenset()),
}

EXIT_CODE_FALLBACKS = {
    2: "INVALID_ARGUMENTS",
    3: "DOCUMENT_PARSE_ERROR",
    4: "REVIEW_PACK_INVALID",
    5: "MODEL_UNAVAILABLE",
    6: "MODEL_RESPONSE_INVALID",
    7: "INTERNAL_ERROR",
    8: "ANALYSIS_TIMEOUT",
}


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ReviewJobErrorMapper:
    """Map untrusted process failures to a finite user-safe error catalog."""

    def __init__(self, *, diagnostic_limit: int = DEFAULT_DIAGNOSTIC_LIMIT) -> None:
        if diagnostic_limit < 1:
            raise ValueError("diagnostic_limit must be positive")
        self._diagnostic_limit = diagnostic_limit

    def from_process(
        self,
        execution: ProcessExecutionResult,
        workspace: RunWorkspace,
        *,
        expected_run_id: str,
    ) -> ReviewJobFailure:
        if execution.exit_code == 0:
            raise ValueError("a successful process cannot be mapped as a failure")
        reported_code, reported_stage = self._read_structured_error(
            workspace, expected_run_id=expected_run_id
        )
        code = EXIT_CODE_FALLBACKS.get(execution.exit_code, "CORE_PROCESS_FAILED")
        descriptor = ERROR_CATALOG.get(reported_code or "")
        if descriptor is not None and execution.exit_code in descriptor.exit_codes:
            code = reported_code or code
        else:
            descriptor = ERROR_CATALOG[code]

        diagnostic_parts = [f"exit_code={execution.exit_code}", f"mapped_error={code}"]
        if reported_code is not None:
            diagnostic_parts.append(f"reported_error={reported_code}")
        if reported_stage is not None:
            diagnostic_parts.append(f"stage={reported_stage}")
        stderr = _sanitize_diagnostic(execution.stderr.utf8())
        if stderr:
            diagnostic_parts.append(f"stderr={stderr}")
        if execution.stderr.truncated:
            diagnostic_parts.append("stderr_truncated=true")
        diagnostic = _truncate(
            _sanitize_diagnostic("; ".join(diagnostic_parts)),
            self._diagnostic_limit,
        )
        return ReviewJobFailure(
            error_code=code,
            user_message=descriptor.user_message,
            diagnostic_message=diagnostic,
            retriable=descriptor.retriable,
        )

    def from_acceptance_error(
        self,
        error: ReviewResultAcceptanceError,
        *,
        diagnostic: str | None = None,
    ) -> ReviewJobFailure:
        if isinstance(error, IncompatibleSchemaVersionError):
            code = "CORE_SCHEMA_INCOMPATIBLE"
        elif isinstance(error, ResultIdentityMismatchError):
            code = "CORE_RESULT_MISMATCH"
        else:
            code = "CORE_RESULT_INVALID"
        descriptor = ERROR_CATALOG[code]
        internal = f"acceptance_error={type(error).__name__}"
        if diagnostic:
            internal = f"{internal}; detail={_sanitize_diagnostic(diagnostic)}"
        return ReviewJobFailure(
            error_code=code,
            user_message=descriptor.user_message,
            diagnostic_message=_truncate(internal, self._diagnostic_limit),
            retriable=descriptor.retriable,
        )

    @staticmethod
    def _read_structured_error(
        workspace: RunWorkspace, *, expected_run_id: str
    ) -> tuple[str | None, str | None]:
        path = workspace.resolve("output/result.json")
        if path.is_symlink() or not path.is_file():
            return None, None
        try:
            if not 0 < path.stat().st_size <= MAX_FAILURE_RESULT_BYTES:
                return None, None
            payload = json.loads(path.read_text(encoding="utf-8", errors="strict"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None, None
        if (
            not isinstance(payload, dict)
            or payload.get("status") != "failed"
            or payload.get("run_id") != expected_run_id
            or not isinstance(payload.get("error"), dict)
        ):
            return None, None
        error = payload["error"]
        code = error.get("code")
        stage = error.get("stage")
        return (
            code if isinstance(code, str) else None,
            stage if isinstance(stage, str) else None,
        )


class ReviewJobFailureService:
    """Persist mapped failures without scheduling automatic retries."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        mapper: ReviewJobErrorMapper | None = None,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._mapper = mapper or ReviewJobErrorMapper()
        self._clock = clock

    def record_process_failure(
        self,
        job_id: UUID,
        execution: ProcessExecutionResult,
        workspace: RunWorkspace,
        *,
        expected_run_id: str,
    ) -> ReviewJobModel:
        failure = self._mapper.from_process(execution, workspace, expected_run_id=expected_run_id)
        with self._session_factory.begin() as session:
            repository = ReviewJobRepository(session)
            if failure.error_code == "ANALYSIS_TIMEOUT":
                return repository.timed_out(job_id, at=execution.finished_at, failure=failure)
            if failure.error_code == "ANALYSIS_CANCELLED":
                return repository.cancel(job_id, at=execution.finished_at, failure=failure)
            return repository.fail(job_id, at=execution.finished_at, failure=failure)

    def record_acceptance_failure(
        self,
        job_id: UUID,
        error: ReviewResultAcceptanceError,
        *,
        diagnostic: str | None = None,
    ) -> ReviewJobModel:
        failure = self._mapper.from_acceptance_error(error, diagnostic=diagnostic)
        with self._session_factory.begin() as session:
            return ReviewJobRepository(session).fail(
                job_id,
                at=self._clock(),
                failure=failure,
            )


def _sanitize_diagnostic(value: str) -> str:
    printable = "".join(character if character.isprintable() else " " for character in value)
    return _WHITESPACE_PATTERN.sub(" ", printable).strip()


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    marker = "...[truncated]"
    return value[: max(0, limit - len(marker))] + marker[:limit]
