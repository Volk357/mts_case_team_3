from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from contextlib import suppress
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session, sessionmaker

from docreview_api.db import Base, create_database_engine, create_session_factory
from docreview_api.db.models import (
    CompanyModel,
    DocumentModel,
    ReviewJobModel,
    ReviewPackReferenceModel,
)
from docreview_api.models.review_job_state import ReviewJobStatus
from docreview_api.services.process_runner import ProcessRunner
from docreview_api.services.review_job_control import ReviewJobControlService
from docreview_api.services.review_job_errors import ERROR_CATALOG, ReviewJobFailureService
from docreview_api.services.review_job_executor import AnalysisJobExecutor
from docreview_api.services.review_job_queue import DatabaseReviewJobQueue
from docreview_api.services.review_result_receiver import ReviewResultReceiver
from docreview_api.services.run_workspace import RunWorkspaceManager
from docreview_api.workers.review_worker import (
    ReviewJobWorker,
    analysis_process_environment,
    resolve_analysis_executable,
)

SCHEMA_PATH = Path(__file__).resolve().parents[3] / "contracts" / "review-result.schema.json"


def test_mock_process_environment_is_explicit_and_real_core_stays_isolated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DOCREVIEW_MOCK_PROFILE", "demo")
    monkeypatch.setenv("DOCREVIEW_MOCK_SCENARIO", "standard-12")
    monkeypatch.setenv("UNRELATED_SECRET", "must-not-cross")

    assert analysis_process_environment("docreview") == {}
    assert analysis_process_environment("docreview-mock") == {
        "DOCREVIEW_MOCK_PROFILE": "demo",
        "DOCREVIEW_MOCK_SCENARIO": "standard-12",
    }


def test_resolve_analysis_executable_finds_console_script_next_to_python(tmp_path: Path) -> None:
    filename = "docreview.exe" if sys.platform == "win32" else "docreview"
    executable = tmp_path / filename
    executable.touch()

    assert resolve_analysis_executable("docreview", executable_directory=tmp_path) == str(
        executable.resolve()
    )
    assert (
        resolve_analysis_executable("tools/docreview", executable_directory=tmp_path)
        == "tools/docreview"
    )


def seed_queued_job(
    sessions: sessionmaker[Session], documents_root: Path, review_packs_root: Path
) -> UUID:
    content = b"%PDF-1.7\nworker integration fixture\n%%EOF"
    document_id = uuid4()
    company_id = uuid4()
    pack_id = uuid4()
    documents_root.mkdir(parents=True)
    (documents_root / f"{document_id.hex}.pdf").write_bytes(content)
    (review_packs_root / "requirements").mkdir(parents=True)
    job = ReviewJobModel(
        run_id=f"worker-{uuid4().hex}",
        company_id=company_id,
        document_id=document_id,
        review_pack_reference_id=pack_id,
        status=ReviewJobStatus.QUEUED,
    )
    with sessions.begin() as session:
        session.add(CompanyModel(id=company_id, slug=company_id.hex, display_name="Company"))
        session.add(
            DocumentModel(
                id=document_id,
                company_id=company_id,
                original_filename="document.pdf",
                media_type="application/pdf",
                size_bytes=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
                storage_key=f"{document_id.hex}.pdf",
            )
        )
        session.add(
            ReviewPackReferenceModel(
                id=pack_id,
                company_id=company_id,
                pack_key="requirements",
                version="mock-success-1.0",
                display_name="Requirements",
                locator="requirements",
            )
        )
        session.add(job)
    return job.id


def build_test_worker(
    tmp_path: Path, scenario: str, database_url: str
) -> tuple[ReviewJobWorker, sessionmaker[Session], UUID]:
    engine = create_database_engine(database_url)
    Base.metadata.create_all(engine)
    sessions = create_session_factory(engine)
    documents_root = tmp_path / "documents"
    review_packs_root = tmp_path / "review-packs"
    job_id = seed_queued_job(sessions, documents_root, review_packs_root)
    queue = DatabaseReviewJobQueue(sessions)
    runner = ProcessRunner(
        (sys.executable, "-m", "docreview_mock"),
        environment={
            "DOCREVIEW_MOCK_PROFILE": "test",
            "DOCREVIEW_MOCK_SCENARIO": scenario,
        },
    )
    executor = AnalysisJobExecutor(
        sessions,
        queue,
        documents_root=documents_root,
        review_packs_root=review_packs_root,
        workspace_manager=RunWorkspaceManager(tmp_path / "runs"),
        process_runner=runner,
        control=ReviewJobControlService(sessions),
        failure_service=ReviewJobFailureService(sessions),
        result_receiver=ReviewResultReceiver(sessions, schema_path=SCHEMA_PATH),
        timeout_seconds=0.1 if scenario == "timeout" else 5,
        termination_grace_seconds=0.1,
    )
    worker = ReviewJobWorker(
        queue,
        executor,
        stale_after=timedelta(minutes=10),
        poll_interval_seconds=0.01,
    )
    return worker, sessions, job_id


@pytest.mark.parametrize("scenario", ["empty", "standard-12", "maximum-20"])
@pytest.mark.anyio
async def test_worker_completes_all_success_scenarios(
    tmp_path: Path, scenario: str, database_url: str
) -> None:
    worker, sessions, job_id = build_test_worker(tmp_path, scenario, database_url)

    assert await worker.run_once()

    with sessions() as session:
        job = session.get(ReviewJobModel, job_id)
        assert job is not None and job.status is ReviewJobStatus.COMPLETED
        expected_count = {"empty": 0, "standard-12": 12, "maximum-20": 20}[scenario]
        assert len(job.findings) == expected_count


@pytest.mark.parametrize(
    ("scenario", "status", "error_code"),
    [
        ("document-parse-error", ReviewJobStatus.FAILED, "DOCUMENT_PARSE_ERROR"),
        ("review-pack-not-found", ReviewJobStatus.FAILED, "REVIEW_PACK_NOT_FOUND"),
        ("model-unavailable", ReviewJobStatus.FAILED, "MODEL_UNAVAILABLE"),
        ("invalid-json", ReviewJobStatus.FAILED, "MODEL_RESPONSE_INVALID"),
        ("incompatible-schema-version", ReviewJobStatus.FAILED, "CORE_SCHEMA_INCOMPATIBLE"),
        ("timeout", ReviewJobStatus.TIMED_OUT, "ANALYSIS_TIMEOUT"),
        ("crash", ReviewJobStatus.FAILED, "INTERNAL_ERROR"),
        ("missing-result-after-success", ReviewJobStatus.FAILED, "CORE_RESULT_INVALID"),
    ],
)
@pytest.mark.anyio
async def test_worker_terminalizes_every_failure_scenario(
    tmp_path: Path,
    scenario: str,
    status: ReviewJobStatus,
    error_code: str,
    database_url: str,
) -> None:
    worker, sessions, job_id = build_test_worker(tmp_path, scenario, database_url)

    assert await worker.run_once()

    with sessions() as session:
        job = session.get(ReviewJobModel, job_id)
        assert job is not None and job.status is status
        assert job.error_code == error_code
        assert job.raw_result is None
        assert job.user_error_message
        assert "mock:" not in job.user_error_message


@pytest.mark.anyio
async def test_worker_writes_reproducible_private_process_diagnostic(tmp_path: Path) -> None:
    worker, sessions, job_id = build_test_worker(tmp_path, "model-unavailable")

    assert await worker.run_once()

    with sessions() as session:
        job = session.get(ReviewJobModel, job_id)
        assert job is not None
        run_id = job.run_id
    report = json.loads(
        (tmp_path / "runs" / run_id / "artifacts" / "integration-diagnostic.json").read_text(
            encoding="utf-8"
        )
    )
    assert report["format_version"] == "1.0"
    assert report["run_id"] == run_id
    assert report["command"][0:3] == [sys.executable, "-m", "docreview_mock"]
    assert report["command"][-2:] == [
        "--artifacts-dir",
        str(tmp_path / "runs" / run_id / "artifacts"),
    ]
    assert report["exit_code"] == 5
    assert set(report["stderr"]) == {"text", "truncated"}
    assert report["contract_validation_errors"] == []


@pytest.mark.anyio
async def test_worker_records_exact_contract_rejection_for_core_owner(tmp_path: Path) -> None:
    worker, sessions, job_id = build_test_worker(tmp_path, "incompatible-schema-version")

    assert await worker.run_once()

    with sessions() as session:
        job = session.get(ReviewJobModel, job_id)
        assert job is not None
        run_id = job.run_id
        assert "schema major 2 is unsupported" in (job.diagnostic_message or "")
    report = json.loads(
        (tmp_path / "runs" / run_id / "artifacts" / "integration-diagnostic.json").read_text(
            encoding="utf-8"
        )
    )
    assert report["exit_code"] == 0
    assert report["contract_validation_errors"] == ["ReviewResult schema major 2 is unsupported"]


class FailingExecutor:
    async def execute(self, job_id: UUID) -> None:
        del job_id
        raise RuntimeError("secret detail must not become user-visible")


@pytest.mark.anyio
async def test_worker_survives_executor_error_and_keeps_diagnostic_internal(
    tmp_path: Path, database_url: str
) -> None:
    engine = create_database_engine(database_url)
    Base.metadata.create_all(engine)
    sessions = create_session_factory(engine)
    job_id = seed_queued_job(sessions, tmp_path / "documents", tmp_path / "packs")
    queue = DatabaseReviewJobQueue(sessions)
    worker = ReviewJobWorker(
        queue,
        FailingExecutor(),
        stale_after=timedelta(minutes=10),
        poll_interval_seconds=0.01,
    )

    assert await worker.run_once()

    with sessions() as session:
        job = session.get(ReviewJobModel, job_id)
        assert job is not None and job.status is ReviewJobStatus.FAILED
        assert job.error_code == "WORKER_EXECUTION_ERROR"
        assert job.user_error_message == ERROR_CATALOG["WORKER_EXECUTION_ERROR"].user_message
        assert job.diagnostic_message == "Worker executor raised RuntimeError."
        assert "secret detail" not in job.user_error_message


@pytest.mark.anyio
async def test_worker_shutdown_terminates_child_and_marks_job_interrupted(
    tmp_path: Path, database_url: str
) -> None:
    worker, sessions, job_id = build_test_worker(tmp_path, "timeout", database_url)
    task = asyncio.create_task(worker.run_once())
    for _ in range(100):
        with sessions() as session:
            job = session.get(ReviewJobModel, job_id)
            if job is not None and job.process_pid is not None:
                break
        await asyncio.sleep(0.01)
    else:
        pytest.fail("worker did not start the child process")

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    with sessions() as session:
        job = session.get(ReviewJobModel, job_id)
        assert job is not None and job.status is ReviewJobStatus.FAILED
        assert job.error_code == "WORKER_INTERRUPTED"
        assert job.error_retriable is True


@pytest.mark.anyio
async def test_new_worker_processes_job_left_queued_before_restart(
    tmp_path: Path, database_url: str
) -> None:
    worker, sessions, job_id = build_test_worker(tmp_path, "empty", database_url)
    del worker

    queue = DatabaseReviewJobQueue(sessions)

    class CompletingExecutor:
        def __init__(self) -> None:
            self.seen: list[UUID] = []

        async def execute(self, claimed_id: UUID) -> None:
            self.seen.append(claimed_id)

    executor = CompletingExecutor()
    restarted = ReviewJobWorker(
        queue,
        executor,
        stale_after=timedelta(minutes=10),
        poll_interval_seconds=0.01,
    )
    assert restarted.recover_after_restart() == ()
    assert await restarted.run_once()
    assert executor.seen == [job_id]


@pytest.mark.anyio
async def test_heartbeat_keeps_ticking_during_a_long_job(tmp_path: Path) -> None:
    """Отметка живости не должна зависеть от того, занят воркер или ждёт.

    Анализ держит цикл минутами. Если отмечаться только между заданиями,
    health объявит воркер мёртвым ровно тогда, когда он работает, — то есть
    проверка будет вредной, а не бесполезной.
    """

    heartbeat = tmp_path / "beat"
    started = asyncio.Event()
    release = asyncio.Event()

    class SlowQueue:
        def __init__(self) -> None:
            self.handed_out = False

        def claim_next(self):
            if self.handed_out:
                return None
            self.handed_out = True
            return SimpleNamespace(id=uuid4(), run_id="review-slow")

        def recover_stale(self, *, stale_after):
            del stale_after
            return ()

        def fail_claimed(self, job_id, *, diagnostic):
            del job_id, diagnostic

    class SlowExecutor:
        async def execute(self, job_id) -> None:
            del job_id
            started.set()
            await release.wait()

    worker = ReviewJobWorker(
        SlowQueue(),
        SlowExecutor(),
        stale_after=timedelta(seconds=60),
        poll_interval_seconds=0.05,
        heartbeat_path=heartbeat,
    )

    stop = asyncio.Event()
    task = asyncio.create_task(worker.run_forever(stop))
    await asyncio.wait_for(started.wait(), timeout=5)

    first = heartbeat.read_text(encoding="utf-8")
    await asyncio.sleep(0.25)  # задание всё ещё выполняется
    second = heartbeat.read_text(encoding="utf-8")

    release.set()
    stop.set()
    with suppress(TimeoutError):
        await asyncio.wait_for(task, timeout=5)
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task

    assert second != first, "отметка обязана обновляться во время задания"
