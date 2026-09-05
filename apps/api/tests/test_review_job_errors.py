import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from docreview_api.db import Base, create_database_engine, create_session_factory
from docreview_api.db.models import (
    CompanyModel,
    DocumentModel,
    ReviewJobModel,
    ReviewPackReferenceModel,
)
from docreview_api.models import ReviewJobStatus
from docreview_api.repositories import ReviewJobRepository
from docreview_api.services import (
    CapturedProcessStream,
    IncompatibleSchemaVersionError,
    ProcessExecutionResult,
    ResultJsonError,
    ReviewJobErrorMapper,
    ReviewJobFailureService,
    RunWorkspace,
    RunWorkspaceManager,
)

QUEUED_AT = datetime(2026, 9, 3, 15, 59, 59, tzinfo=UTC)
STARTED_AT = QUEUED_AT + timedelta(seconds=1)
FINISHED_AT = STARTED_AT + timedelta(seconds=5)


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


def workspace_with_error(
    tmp_path: Path,
    *,
    run_id: str,
    error_code: str | None = None,
    stage: str = "pipeline",
) -> RunWorkspace:
    workspace = RunWorkspaceManager(tmp_path / "runs").prepare(run_id)
    if error_code is not None:
        workspace.resolve("output/result.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "run_id": run_id,
                    "status": "failed",
                    "error": {
                        "code": error_code,
                        "stage": stage,
                        "message": "untrusted core details",
                        "retriable": True,
                    },
                }
            ),
            encoding="utf-8",
        )
    return workspace


def execution(exit_code: int, *, stderr: str = "core diagnostic") -> ProcessExecutionResult:
    return ProcessExecutionResult(
        pid=4242,
        started_at=STARTED_AT,
        finished_at=FINISHED_AT,
        exit_code=exit_code,
        stdout=CapturedProcessStream(content=b"", truncated=False),
        stderr=CapturedProcessStream(content=stderr.encode(), truncated=False),
    )


@pytest.mark.parametrize(
    ("exit_code", "reported_code", "expected_code", "retriable"),
    [
        (2, "INVALID_ARGUMENTS", "INVALID_ARGUMENTS", False),
        (3, "DOCUMENT_PARSE_ERROR", "DOCUMENT_PARSE_ERROR", False),
        (4, "REVIEW_PACK_NOT_FOUND", "REVIEW_PACK_NOT_FOUND", False),
        (5, "MODEL_UNAVAILABLE", "MODEL_UNAVAILABLE", True),
        (5, "MODEL_AUTH_FAILED", "MODEL_AUTH_FAILED", False),
        (6, "MODEL_RESPONSE_INVALID", "MODEL_RESPONSE_INVALID", True),
        (7, "INTERNAL_ERROR", "INTERNAL_ERROR", False),
        (8, "ANALYSIS_TIMEOUT", "ANALYSIS_TIMEOUT", True),
        (8, "ANALYSIS_CANCELLED", "ANALYSIS_CANCELLED", False),
        (99, None, "CORE_PROCESS_FAILED", False),
    ],
)
def test_exit_codes_map_to_safe_domain_failures(
    tmp_path: Path,
    exit_code: int,
    reported_code: str | None,
    expected_code: str,
    retriable: bool,
) -> None:
    workspace = workspace_with_error(
        tmp_path, run_id=f"review-map-{exit_code}-{expected_code}", error_code=reported_code
    )

    failure = ReviewJobErrorMapper().from_process(
        execution(exit_code), workspace, expected_run_id=workspace.run_id
    )

    assert failure.error_code == expected_code
    assert failure.retriable is retriable
    assert "untrusted core details" not in failure.user_message
    assert "core diagnostic" not in failure.user_message
    assert "core diagnostic" in (failure.diagnostic_message or "")


def test_mismatched_structured_code_uses_exit_code_fallback(tmp_path: Path) -> None:
    workspace = workspace_with_error(
        tmp_path,
        run_id="review-mismatch",
        error_code="MODEL_UNAVAILABLE",
    )

    failure = ReviewJobErrorMapper().from_process(
        execution(3), workspace, expected_run_id=workspace.run_id
    )

    assert failure.error_code == "DOCUMENT_PARSE_ERROR"
    assert failure.retriable is False


def test_diagnostic_is_sanitized_and_bounded(tmp_path: Path) -> None:
    workspace = workspace_with_error(tmp_path, run_id="review-diagnostic")
    failure = ReviewJobErrorMapper(diagnostic_limit=80).from_process(
        execution(7, stderr="secret-looking text\n" + "x" * 500),
        workspace,
        expected_run_id=workspace.run_id,
    )

    assert failure.diagnostic_message is not None
    assert len(failure.diagnostic_message) == 80
    assert "\n" not in failure.diagnostic_message
    assert failure.diagnostic_message.endswith("...[truncated]")
    assert "secret-looking text" not in failure.user_message


def seed_running_job(sessions: sessionmaker[Session], *, run_id: str) -> UUID:
    with sessions.begin() as session:
        company = CompanyModel(slug=run_id, display_name="Test")
        session.add(company)
        session.flush()
        document = DocumentModel(
            company_id=company.id,
            original_filename="document.pdf",
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
            locator="review-packs/requirements",
        )
        session.add_all([document, review_pack])
        session.flush()
        job = ReviewJobModel(
            run_id=run_id,
            company_id=company.id,
            document_id=document.id,
            review_pack_reference_id=review_pack.id,
            status=ReviewJobStatus.QUEUED,
            queued_at=QUEUED_AT,
            created_at=QUEUED_AT,
            updated_at=QUEUED_AT,
        )
        ReviewJobRepository(session).add(job)
        ReviewJobRepository(session).start(job.id, at=STARTED_AT, process_pid=4242)
        return job.id


def test_failure_service_persists_diagnostics_without_automatic_retry(
    tmp_path: Path, sessions: sessionmaker[Session]
) -> None:
    run_id = "review-model-failure"
    job_id = seed_running_job(sessions, run_id=run_id)
    workspace = workspace_with_error(
        tmp_path,
        run_id=run_id,
        error_code="MODEL_UNAVAILABLE",
        stage="semantic_review",
    )

    ReviewJobFailureService(sessions).record_process_failure(
        job_id,
        execution(5, stderr="internal endpoint unavailable"),
        workspace,
        expected_run_id=run_id,
    )

    with sessions() as restarted_session:
        job = ReviewJobRepository(restarted_session).require(job_id)
        assert job.status is ReviewJobStatus.FAILED
        assert job.error_code == "MODEL_UNAVAILABLE"
        assert job.user_error_message is not None
        assert "endpoint" not in job.user_error_message
        assert "endpoint" in (job.diagnostic_message or "")
        assert job.error_retriable is True
        assert restarted_session.scalar(select(func.count()).select_from(ReviewJobModel)) == 1


def test_exit_code_eight_uses_timeout_terminal_state(
    tmp_path: Path, sessions: sessionmaker[Session]
) -> None:
    run_id = "review-core-timeout"
    job_id = seed_running_job(sessions, run_id=run_id)
    workspace = workspace_with_error(tmp_path, run_id=run_id, error_code="ANALYSIS_TIMEOUT")

    ReviewJobFailureService(sessions).record_process_failure(
        job_id, execution(8), workspace, expected_run_id=run_id
    )

    with sessions() as session:
        assert ReviewJobRepository(session).require(job_id).status is ReviewJobStatus.TIMED_OUT


@pytest.mark.parametrize(
    ("error", "expected_code"),
    [
        (ResultJsonError("bad json"), "CORE_RESULT_INVALID"),
        (IncompatibleSchemaVersionError("major 2"), "CORE_SCHEMA_INCOMPATIBLE"),
    ],
)
def test_acceptance_errors_become_safe_failed_jobs(
    sessions: sessionmaker[Session],
    error: Exception,
    expected_code: str,
) -> None:
    run_id = f"review-accept-{expected_code.lower()}"
    job_id = seed_running_job(sessions, run_id=run_id)

    ReviewJobFailureService(sessions, clock=lambda: FINISHED_AT).record_acceptance_failure(
        job_id,
        error,  # type: ignore[arg-type]
        diagnostic="private parser detail",
    )

    with sessions() as session:
        job = ReviewJobRepository(session).require(job_id)
        assert job.status is ReviewJobStatus.FAILED
        assert job.error_code == expected_code
        assert "private parser detail" not in (job.user_error_message or "")
        assert "private parser detail" in (job.diagnostic_message or "")
