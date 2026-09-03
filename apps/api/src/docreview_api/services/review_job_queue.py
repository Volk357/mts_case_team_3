"""Transport-neutral queue contract backed by the application database for the MVP."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from docreview_api.models.review_job_state import ReviewJobFailure
from docreview_api.repositories.database import ReviewJobRepository
from docreview_api.services.review_job_errors import ERROR_CATALOG


@dataclass(frozen=True, slots=True)
class ClaimedReviewJob:
    id: UUID
    run_id: str


class ReviewJobQueue(Protocol):
    """Boundary that a future Celery/Redis adapter can implement unchanged."""

    def claim_next(self) -> ClaimedReviewJob | None: ...

    def recover_stale(self, *, stale_after: timedelta) -> tuple[UUID, ...]: ...

    def attach_process(self, job_id: UUID, *, process_pid: int) -> bool: ...

    def fail_claimed(self, job_id: UUID, *, diagnostic: str) -> bool: ...

    def interrupt_claimed(self, job_id: UUID, *, diagnostic: str) -> bool: ...


def _utc_now() -> datetime:
    return datetime.now(UTC)


class DatabaseReviewJobQueue:
    """Durable FIFO queue using short atomic database transactions."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock

    def claim_next(self) -> ClaimedReviewJob | None:
        with self._session_factory.begin() as session:
            job = ReviewJobRepository(session).claim_next(at=self._clock())
            if job is None:
                return None
            return ClaimedReviewJob(id=job.id, run_id=job.run_id)

    def recover_stale(self, *, stale_after: timedelta) -> tuple[UUID, ...]:
        if stale_after <= timedelta(0):
            raise ValueError("stale_after must be positive")
        now = self._clock()
        failure = self._failure(
            "WORKER_INTERRUPTED",
            "Worker recovered an abandoned running job after restart.",
        )
        with self._session_factory.begin() as session:
            return ReviewJobRepository(session).fail_stale_running(
                updated_before=now - stale_after,
                at=now,
                failure=failure,
            )

    def attach_process(self, job_id: UUID, *, process_pid: int) -> bool:
        with self._session_factory.begin() as session:
            return ReviewJobRepository(session).attach_process(job_id, process_pid=process_pid)

    def fail_claimed(self, job_id: UUID, *, diagnostic: str) -> bool:
        return self._fail_claimed(
            job_id, failure=self._failure("WORKER_EXECUTION_ERROR", diagnostic)
        )

    def interrupt_claimed(self, job_id: UUID, *, diagnostic: str) -> bool:
        return self._fail_claimed(job_id, failure=self._failure("WORKER_INTERRUPTED", diagnostic))

    def _fail_claimed(self, job_id: UUID, *, failure: ReviewJobFailure) -> bool:
        with self._session_factory.begin() as session:
            return ReviewJobRepository(session).fail_running(
                job_id,
                at=self._clock(),
                failure=failure,
            )

    @staticmethod
    def _failure(code: str, diagnostic: str) -> ReviewJobFailure:
        descriptor = ERROR_CATALOG[code]
        return ReviewJobFailure(
            error_code=code,
            user_message=descriptor.user_message,
            diagnostic_message=diagnostic,
            retriable=descriptor.retriable,
        )
