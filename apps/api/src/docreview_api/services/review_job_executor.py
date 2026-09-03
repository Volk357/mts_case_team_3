"""Execute one claimed review job through the Analysis Core process contract."""

from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from docreview_api.db.models import ReviewJobModel
from docreview_api.repositories.database import ReviewJobRepository
from docreview_api.services.process_runner import AnalysisProcessRequest, ProcessRunner
from docreview_api.services.review_job_control import ReviewJobControlService
from docreview_api.services.review_job_errors import ReviewJobFailureService
from docreview_api.services.review_job_queue import ReviewJobQueue
from docreview_api.services.review_result_receiver import (
    ReviewResultAcceptanceError,
    ReviewResultReceiver,
)
from docreview_api.services.run_workspace import RunWorkspace, RunWorkspaceManager


class WorkerInputError(ValueError):
    """A persisted worker input cannot be resolved inside configured storage."""


@dataclass(frozen=True, slots=True)
class _JobInputs:
    run_id: str
    document_id: UUID
    document_storage_key: str
    review_pack_locator: str


class AnalysisJobExecutor:
    """Filesystem/process adapter behind the transport-neutral worker boundary."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        queue: ReviewJobQueue,
        *,
        documents_root: Path,
        review_packs_root: Path,
        workspace_manager: RunWorkspaceManager,
        process_runner: ProcessRunner,
        control: ReviewJobControlService,
        failure_service: ReviewJobFailureService,
        result_receiver: ReviewResultReceiver,
        timeout_seconds: float,
        termination_grace_seconds: float,
    ) -> None:
        self._session_factory = session_factory
        self._queue = queue
        self._documents_root = documents_root.resolve()
        self._review_packs_root = review_packs_root.resolve()
        self._workspace_manager = workspace_manager
        self._process_runner = process_runner
        self._control = control
        self._failure_service = failure_service
        self._result_receiver = result_receiver
        self._timeout_seconds = timeout_seconds
        self._termination_grace_seconds = termination_grace_seconds

    async def execute(self, job_id: UUID) -> None:
        inputs = self._load_inputs(job_id)
        workspace = self._workspace_manager.prepare(inputs.run_id)
        document_path = self._copy_document(inputs, workspace)
        review_pack_path = self._resolve_stored_path(
            self._review_packs_root,
            inputs.review_pack_locator,
            kind="Review Pack",
        )
        process = await self._process_runner.start(
            AnalysisProcessRequest(
                run_id=inputs.run_id,
                document_path=document_path,
                review_pack_path=review_pack_path,
                workspace=workspace,
            )
        )
        if not self._queue.attach_process(job_id, process_pid=process.pid):
            await process.terminate(grace_period_seconds=self._termination_grace_seconds)
            return

        try:
            controlled = await self._control.wait_for_process(
                job_id,
                process,
                timeout_seconds=self._timeout_seconds,
                termination_grace_seconds=self._termination_grace_seconds,
            )
        except asyncio.CancelledError:
            try:
                self._queue.interrupt_claimed(
                    job_id,
                    diagnostic="Worker stopped while Analysis Core was running.",
                )
            finally:
                await process.terminate(grace_period_seconds=self._termination_grace_seconds)
            raise
        if controlled.timed_out or controlled.cancelled:
            return
        execution = controlled.execution
        if execution.exit_code != 0:
            self._failure_service.record_process_failure(
                job_id,
                execution,
                workspace,
                expected_run_id=inputs.run_id,
            )
            return
        try:
            self._result_receiver.receive(job_id, workspace, execution)
        except ReviewResultAcceptanceError as error:
            self._failure_service.record_acceptance_failure(job_id, error)

    def _load_inputs(self, job_id: UUID) -> _JobInputs:
        with self._session_factory() as session:
            job: ReviewJobModel = ReviewJobRepository(session).require(job_id)
            return _JobInputs(
                run_id=job.run_id,
                document_id=job.document_id,
                document_storage_key=job.document.storage_key,
                review_pack_locator=job.review_pack.locator,
            )

    def _copy_document(self, inputs: _JobInputs, workspace: RunWorkspace) -> Path:
        source = self._resolve_stored_path(
            self._documents_root,
            inputs.document_storage_key,
            kind="document",
        )
        if not source.is_file():
            raise WorkerInputError("document is not a readable file")
        destination = workspace.input_dir / f"{inputs.document_id.hex}{source.suffix.casefold()}"
        shutil.copyfile(source, destination)
        return destination.resolve()

    @staticmethod
    def _resolve_stored_path(root: Path, locator: str, *, kind: str) -> Path:
        posix = PurePosixPath(locator)
        if (
            not locator
            or posix.is_absolute()
            or PureWindowsPath(locator).is_absolute()
            or "\\" in locator
            or ".." in posix.parts
        ):
            raise WorkerInputError(f"{kind} locator is unsafe")
        candidate = root.joinpath(*posix.parts).resolve()
        if not candidate.is_relative_to(root) or not candidate.exists():
            raise WorkerInputError(f"{kind} is unavailable")
        return candidate
