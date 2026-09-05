"""Separate durable ReviewJob worker process."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import timedelta
from typing import Protocol
from uuid import UUID

from docreview_api.config import Settings, get_settings
from docreview_api.db import create_database_engine, create_session_factory
from docreview_api.services.process_runner import ProcessRunner
from docreview_api.services.review_job_control import ReviewJobControlService
from docreview_api.services.review_job_errors import ReviewJobFailureService
from docreview_api.services.review_job_executor import AnalysisJobExecutor
from docreview_api.services.review_job_queue import DatabaseReviewJobQueue, ReviewJobQueue
from docreview_api.services.review_result_receiver import ReviewResultReceiver
from docreview_api.services.run_workspace import RunWorkspaceManager

LOGGER = logging.getLogger(__name__)


class ReviewJobExecutor(Protocol):
    async def execute(self, job_id: UUID) -> None: ...


class ReviewJobWorker:
    """Poll a queue and execute one atomically claimed job at a time."""

    def __init__(
        self,
        queue: ReviewJobQueue,
        executor: ReviewJobExecutor,
        *,
        stale_after: timedelta,
        poll_interval_seconds: float,
    ) -> None:
        if stale_after <= timedelta(0):
            raise ValueError("stale_after must be positive")
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        self._queue = queue
        self._executor = executor
        self._stale_after = stale_after
        self._poll_interval_seconds = poll_interval_seconds

    def recover_after_restart(self) -> tuple[UUID, ...]:
        """Terminalize only jobs whose running lease is older than the safety window."""

        recovered = self._queue.recover_stale(stale_after=self._stale_after)
        if recovered:
            LOGGER.warning("Recovered %d abandoned review job(s)", len(recovered))
        return recovered

    async def run_once(self) -> bool:
        claimed = self._queue.claim_next()
        if claimed is None:
            return False
        try:
            await self._executor.execute(claimed.id)
        except Exception as error:
            LOGGER.exception("Review job execution failed for run %s", claimed.run_id)
            self._queue.fail_claimed(
                claimed.id,
                diagnostic=f"Worker executor raised {type(error).__name__}.",
            )
        return True

    async def run_forever(self, stop_event: asyncio.Event | None = None) -> None:
        stop = stop_event or asyncio.Event()
        self.recover_after_restart()
        while not stop.is_set():
            if await self.run_once():
                continue
            with suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=self._poll_interval_seconds)


def build_worker(settings: Settings) -> ReviewJobWorker:
    engine = create_database_engine(settings.database_url)
    sessions = create_session_factory(engine)
    queue = DatabaseReviewJobQueue(sessions)
    runner = ProcessRunner(
        (settings.analysis_executable,),
        stdout_limit_bytes=settings.process_stdout_limit_bytes,
        stderr_limit_bytes=settings.process_stderr_limit_bytes,
    )
    control = ReviewJobControlService(sessions)
    failure_service = ReviewJobFailureService(sessions)
    receiver = ReviewResultReceiver(
        sessions,
        schema_path=settings.review_result_schema_path,
        max_result_size_bytes=settings.max_review_result_size_bytes,
    )
    executor = AnalysisJobExecutor(
        sessions,
        queue,
        documents_root=settings.documents_dir,
        review_packs_root=settings.review_packs_dir,
        workspace_manager=RunWorkspaceManager(settings.runs_dir),
        process_runner=runner,
        control=control,
        failure_service=failure_service,
        result_receiver=receiver,
        timeout_seconds=settings.analysis_timeout_seconds,
        termination_grace_seconds=settings.process_termination_grace_seconds,
        model_config_path=settings.analysis_model_config_path,
    )
    return ReviewJobWorker(
        queue,
        executor,
        stale_after=timedelta(seconds=settings.worker_stale_after_seconds),
        poll_interval_seconds=settings.worker_poll_interval_seconds,
    )


async def _run() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    await build_worker(settings).run_forever()


def main() -> None:
    with suppress(KeyboardInterrupt):
        asyncio.run(_run())


if __name__ == "__main__":
    main()
