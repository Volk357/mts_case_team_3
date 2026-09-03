"""Timeout and cancellation orchestration for running review jobs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from docreview_api.db.models import ReviewJobModel
from docreview_api.models.review_job_state import ReviewJobFailure
from docreview_api.repositories.database import ReviewJobRepository
from docreview_api.services.process_runner import (
    AnalysisProcessTimeoutError,
    ProcessExecutionResult,
    RunningAnalysisProcess,
)


@dataclass(frozen=True, slots=True)
class ControlledProcessResult:
    """Process result plus the lifecycle decision made by the application."""

    execution: ProcessExecutionResult
    timed_out: bool = False
    cancelled: bool = False


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ReviewJobControlService:
    """Persist timeout/cancellation before stopping a child process."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock

    async def wait_for_process(
        self,
        job_id: UUID,
        process: RunningAnalysisProcess,
        *,
        timeout_seconds: float,
        termination_grace_seconds: float,
    ) -> ControlledProcessResult:
        """Wait for normal completion or atomically record and enforce timeout."""

        try:
            execution = await process.wait(timeout_seconds=timeout_seconds)
        except AnalysisProcessTimeoutError:
            try:
                self.mark_timed_out(job_id)
            finally:
                execution = await process.terminate(grace_period_seconds=termination_grace_seconds)
            return ControlledProcessResult(execution=execution, timed_out=True)
        return ControlledProcessResult(execution=execution)

    async def request_cancellation(
        self,
        job_id: UUID,
        *,
        process: RunningAnalysisProcess | None = None,
        termination_grace_seconds: float = 5.0,
    ) -> ControlledProcessResult | None:
        """Persist cancellation first, then stop the optional in-memory process."""

        self.mark_cancelled(job_id)
        if process is None:
            return None
        execution = await process.terminate(grace_period_seconds=termination_grace_seconds)
        return ControlledProcessResult(execution=execution, cancelled=True)

    def mark_timed_out(self, job_id: UUID) -> ReviewJobModel:
        failure = ReviewJobFailure(
            error_code="ANALYSIS_TIMEOUT",
            user_message="Проверка превысила допустимое время выполнения.",
            diagnostic_message="Analysis Core exceeded the configured overall timeout.",
            retriable=True,
        )
        with self._session_factory.begin() as session:
            return ReviewJobRepository(session).timed_out(
                job_id,
                at=self._clock(),
                failure=failure,
            )

    def mark_cancelled(self, job_id: UUID) -> ReviewJobModel:
        failure = ReviewJobFailure(
            error_code="ANALYSIS_CANCELLED",
            user_message="Проверка отменена.",
            diagnostic_message="Cancellation was requested by the application.",
            retriable=False,
        )
        with self._session_factory.begin() as session:
            return ReviewJobRepository(session).cancel(
                job_id,
                at=self._clock(),
                failure=failure,
            )
