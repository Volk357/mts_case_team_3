import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from docreview_api.db import Base, create_database_engine, create_session_factory
from docreview_api.db.models import (
    CompanyModel,
    DocumentModel,
    ReviewJobModel,
    ReviewPackReferenceModel,
)
from docreview_api.models import (
    InvalidReviewJobTransition,
    ReviewJobStatus,
    prepare_review_result_snapshot,
)
from docreview_api.repositories import ReviewJobRepository
from docreview_api.services import (
    AnalysisProcessRequest,
    ProcessRunner,
    ReviewJobControlService,
    RunWorkspaceManager,
)

def moments() -> tuple[datetime, datetime]:
    """Метки постановки и завершения, отсчитанные от «сейчас».

    Не модульные константы: `updated_at` проставляет сама БД при UPDATE, а
    переход с меткой из прошлого отвергается инвариантом «время не идёт
    назад». Константа, вычисленная при импорте, успевает устареть за время
    полного прогона — тест падал только в общем запуске, а по отдельности
    проходил.
    """

    queued = datetime.now(UTC) - timedelta(seconds=1)
    return queued, queued + timedelta(seconds=30)


@pytest.fixture
def engine(tmp_path: Path, database_url: str) -> Engine:
    database_engine = create_database_engine(database_url)
    Base.metadata.create_all(database_engine)
    try:
        yield database_engine
    finally:
        database_engine.dispose()


@pytest.fixture
def sessions(engine: Engine) -> sessionmaker[Session]:
    return create_session_factory(engine)


def seed_job(sessions: sessionmaker[Session], *, run_id: str, queued_at: datetime) -> UUID:
    with sessions.begin() as session:
        company = CompanyModel(slug=run_id, display_name="Test")
        session.add(company)
        session.flush()
        document = DocumentModel(
            company_id=company.id,
            original_filename="requirements.pdf",
            media_type="application/pdf",
            size_bytes=10,
            sha256="a" * 64,
            storage_key=f"{run_id}/document.pdf",
        )
        review_pack = ReviewPackReferenceModel(
            company_id=company.id,
            pack_key="requirements",
            version="1.0",
            display_name="Requirements",
            locator="review-packs/requirements/1.0",
        )
        session.add_all([document, review_pack])
        session.flush()
        job = ReviewJobModel(
            run_id=run_id,
            company_id=company.id,
            document_id=document.id,
            review_pack_reference_id=review_pack.id,
            status=ReviewJobStatus.QUEUED,
            queued_at=queued_at,
            created_at=queued_at,
            updated_at=queued_at,
        )
        ReviewJobRepository(session).add(job)
        return job.id


def prepare_slow_process(
    tmp_path: Path, *, run_id: str
) -> tuple[ProcessRunner, AnalysisProcessRequest]:
    workspace = RunWorkspaceManager(tmp_path / "runs").prepare(run_id)
    document = workspace.resolve("input/requirements.pdf")
    document.write_bytes(b"%PDF-1.7\nslow process")
    review_pack = tmp_path / "review-pack"
    review_pack.mkdir(exist_ok=True)
    script = tmp_path / f"slow-{run_id}.py"
    script.write_text(
        "import sys, time\ntime.sleep(30)\nsys.stdout.write('late result')\n",
        encoding="utf-8",
    )
    return ProcessRunner((sys.executable, script)), AnalysisProcessRequest(
        run_id=run_id,
        document_path=document,
        review_pack_path=review_pack,
        workspace=workspace,
    )


@pytest.mark.anyio
async def test_timeout_terminates_process_and_persists_timed_out(
    tmp_path: Path, sessions: sessionmaker[Session]
) -> None:
    QUEUED_AT, FINISHED_AT = moments()
    run_id = "review-timeout"
    job_id = seed_job(sessions, run_id=run_id, queued_at=QUEUED_AT)
    runner, request = prepare_slow_process(tmp_path, run_id=run_id)
    process = await runner.start(request)
    with sessions.begin() as session:
        ReviewJobRepository(session).start(job_id, at=QUEUED_AT, process_pid=process.pid)

    outcome = await ReviewJobControlService(sessions, clock=lambda: FINISHED_AT).wait_for_process(
        job_id,
        process,
        timeout_seconds=0.05,
        termination_grace_seconds=0.2,
    )

    assert outcome.timed_out
    assert not outcome.cancelled
    assert not process.is_running
    with sessions() as session:
        job = ReviewJobRepository(session).require(job_id)
        assert job.status is ReviewJobStatus.TIMED_OUT
        assert job.timed_out_at.replace(tzinfo=UTC) == FINISHED_AT
        assert job.error_code == "ANALYSIS_TIMEOUT"
        assert job.error_retriable is True
        assert job.raw_result is None


@pytest.mark.anyio
async def test_cancellation_is_persisted_before_running_process_stops(
    tmp_path: Path, sessions: sessionmaker[Session]
) -> None:
    QUEUED_AT, FINISHED_AT = moments()
    run_id = "review-cancel"
    job_id = seed_job(sessions, run_id=run_id, queued_at=QUEUED_AT)
    runner, request = prepare_slow_process(tmp_path, run_id=run_id)
    process = await runner.start(request)
    with sessions.begin() as session:
        ReviewJobRepository(session).start(job_id, at=QUEUED_AT, process_pid=process.pid)

    outcome = await ReviewJobControlService(
        sessions, clock=lambda: FINISHED_AT
    ).request_cancellation(
        job_id,
        process=process,
        termination_grace_seconds=0.2,
    )

    assert outcome is not None and outcome.cancelled
    assert not process.is_running
    with sessions() as session:
        job = ReviewJobRepository(session).require(job_id)
        assert job.status is ReviewJobStatus.CANCELLED
        assert job.cancelled_at.replace(tzinfo=UTC) == FINISHED_AT
        assert job.error_code == "ANALYSIS_CANCELLED"
        assert job.error_retriable is False


@pytest.mark.anyio
async def test_queued_job_can_be_cancelled_without_a_process(
    sessions: sessionmaker[Session],
) -> None:
    QUEUED_AT, FINISHED_AT = moments()
    job_id = seed_job(sessions, run_id="review-queued-cancel", queued_at=QUEUED_AT)
    control = ReviewJobControlService(sessions, clock=lambda: FINISHED_AT)

    assert await control.request_cancellation(job_id) is None
    # Repeated delivery of the same cancellation request is idempotent.
    assert await control.request_cancellation(job_id) is None

    with sessions() as session:
        job = ReviewJobRepository(session).require(job_id)
        assert job.status is ReviewJobStatus.CANCELLED
        assert job.started_at is None


def test_cancelled_job_rejects_late_completed_result(sessions: sessionmaker[Session]) -> None:
    QUEUED_AT, FINISHED_AT = moments()
    job_id = seed_job(sessions, run_id="review-late", queued_at=QUEUED_AT)
    control = ReviewJobControlService(sessions, clock=lambda: FINISHED_AT)
    control.mark_cancelled(job_id)
    example_path = Path(__file__).resolve().parents[3] / "contracts" / "examples" / "success.json"
    payload = json.loads(example_path.read_text(encoding="utf-8"))
    payload["run_id"] = "review-late"
    payload["document"]["sha256"] = "a" * 64
    payload["review_pack"] = {"id": "requirements", "version": "1.0"}
    snapshot = prepare_review_result_snapshot(payload, expected_document_sha256="a" * 64)

    with sessions.begin() as session, pytest.raises(InvalidReviewJobTransition):
        ReviewJobRepository(session).complete(
            job_id,
            snapshot,
            at=FINISHED_AT + timedelta(seconds=1),
        )

    with sessions() as session:
        job = ReviewJobRepository(session).require(job_id)
        assert job.status is ReviewJobStatus.CANCELLED
        assert job.raw_result is None
