import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
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
from docreview_api.models import InvalidReviewJobTransition, ReviewJobFailure, ReviewJobStatus
from docreview_api.repositories import FindingRepository, ReviewJobRepository
from docreview_api.services import (
    CapturedProcessStream,
    IncompatibleSchemaVersionError,
    NonZeroProcessExitError,
    ProcessExecutionResult,
    ResultEncodingError,
    ResultFileError,
    ResultIdentityMismatchError,
    ResultJsonError,
    ResultSchemaError,
    ReviewResultReceiver,
    RunWorkspace,
    RunWorkspaceManager,
)

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[3]
SCHEMA_PATH = REPOSITORY_DIRECTORY / "contracts" / "review-result.schema.json"
SUCCESS_PATH = REPOSITORY_DIRECTORY / "contracts" / "examples" / "success.json"
STARTED_AT = datetime(2026, 9, 3, 16, 0, tzinfo=UTC)
QUEUED_AT = STARTED_AT - timedelta(seconds=1)
FINISHED_AT = STARTED_AT + timedelta(seconds=5)
PROCESS_PID = 4321


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    database_engine = create_database_engine(f"sqlite:///{(tmp_path / 'receiver.db').as_posix()}")
    Base.metadata.create_all(database_engine)
    try:
        yield database_engine
    finally:
        database_engine.dispose()


@pytest.fixture
def sessions(engine: Engine) -> sessionmaker[Session]:
    return create_session_factory(engine)


def success_payload() -> dict[str, Any]:
    return json.loads(SUCCESS_PATH.read_text(encoding="utf-8"))


def seed_running_job(sessions: sessionmaker[Session], payload: dict[str, Any]) -> UUID:
    with sessions.begin() as session:
        company = CompanyModel(slug="receiver", display_name="Receiver Test")
        session.add(company)
        session.flush()
        document = DocumentModel(
            company_id=company.id,
            original_filename=payload["document"]["filename"],
            media_type="application/pdf",
            size_bytes=10,
            sha256=payload["document"]["sha256"],
            storage_key="receiver/document.pdf",
        )
        review_pack = ReviewPackReferenceModel(
            company_id=company.id,
            pack_key=payload["review_pack"]["id"],
            version=payload["review_pack"]["version"],
            display_name="Test pack",
            locator="review-packs/test",
        )
        session.add_all([document, review_pack])
        session.flush()
        job = ReviewJobModel(
            run_id=payload["run_id"],
            company_id=company.id,
            document_id=document.id,
            review_pack_reference_id=review_pack.id,
            status=ReviewJobStatus.QUEUED,
            queued_at=QUEUED_AT,
            created_at=QUEUED_AT,
            updated_at=QUEUED_AT,
        )
        ReviewJobRepository(session).add(job)
        ReviewJobRepository(session).start(job.id, at=STARTED_AT, process_pid=PROCESS_PID)
        return job.id


def prepare_workspace(tmp_path: Path, payload: dict[str, Any]) -> RunWorkspace:
    workspace = RunWorkspaceManager(tmp_path / "runs").prepare(payload["run_id"])
    workspace.resolve("output/result.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    return workspace


def execution(*, exit_code: int = 0, pid: int = PROCESS_PID) -> ProcessExecutionResult:
    empty = CapturedProcessStream(content=b"", truncated=False)
    return ProcessExecutionResult(
        pid=pid,
        started_at=STARTED_AT,
        finished_at=FINISHED_AT,
        exit_code=exit_code,
        stdout=empty,
        stderr=empty,
    )


def receiver(sessions: sessionmaker[Session], **kwargs: Any) -> ReviewResultReceiver:
    return ReviewResultReceiver(sessions, schema_path=SCHEMA_PATH, **kwargs)


def test_valid_result_is_atomically_persisted_once(
    tmp_path: Path, sessions: sessionmaker[Session]
) -> None:
    payload = success_payload()
    job_id = seed_running_job(sessions, payload)
    workspace = prepare_workspace(tmp_path, payload)
    result_receiver = receiver(sessions)

    first = result_receiver.receive(job_id, workspace, execution())
    second = result_receiver.receive(job_id, workspace, execution())

    assert first.id == second.id == job_id
    with sessions() as restarted_session:
        stored = ReviewJobRepository(restarted_session).require(job_id)
        findings = FindingRepository(restarted_session).list_for_job(job_id)
        assert stored.status is ReviewJobStatus.COMPLETED
        assert stored.raw_result == payload
        assert stored.completed_at.replace(tzinfo=UTC) == FINISHED_AT
        assert len(findings) == len(payload["findings"])


def test_nonzero_exit_code_is_rejected_before_reading_output(
    tmp_path: Path, sessions: sessionmaker[Session]
) -> None:
    payload = success_payload()
    job_id = seed_running_job(sessions, payload)
    workspace = RunWorkspaceManager(tmp_path / "runs").prepare(payload["run_id"])

    with pytest.raises(NonZeroProcessExitError, match="7"):
        receiver(sessions).receive(job_id, workspace, execution(exit_code=7))


@pytest.mark.parametrize(
    ("content", "expected_error"),
    [
        (b"", ResultFileError),
        (b"\xff\xfe", ResultEncodingError),
        (b"{not-json", ResultJsonError),
        (b"[]", ResultJsonError),
    ],
)
def test_missing_empty_invalid_encoding_and_invalid_json_are_rejected(
    tmp_path: Path,
    sessions: sessionmaker[Session],
    content: bytes,
    expected_error: type[Exception],
) -> None:
    payload = success_payload()
    job_id = seed_running_job(sessions, payload)
    workspace = RunWorkspaceManager(tmp_path / "runs").prepare(payload["run_id"])
    if content:
        workspace.resolve("output/result.json").write_bytes(content)

    with pytest.raises(expected_error):
        receiver(sessions).receive(job_id, workspace, execution())


def test_oversized_result_is_rejected(tmp_path: Path, sessions: sessionmaker[Session]) -> None:
    payload = success_payload()
    job_id = seed_running_job(sessions, payload)
    workspace = prepare_workspace(tmp_path, payload)

    with pytest.raises(ResultFileError, match="size"):
        receiver(sessions, max_result_size_bytes=10).receive(job_id, workspace, execution())


def test_json_schema_violation_is_rejected(tmp_path: Path, sessions: sessionmaker[Session]) -> None:
    payload = success_payload()
    job_id = seed_running_job(sessions, payload)
    del payload["findings"][0]["location"]
    workspace = prepare_workspace(tmp_path, payload)

    with pytest.raises(ResultSchemaError, match="schema validation"):
        receiver(sessions).receive(job_id, workspace, execution())

    with sessions() as session:
        stored = ReviewJobRepository(session).require(job_id)
        assert stored.raw_result is None
        assert stored.status is ReviewJobStatus.RUNNING


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload["findings"].append(deepcopy(payload["findings"][0])),
        lambda payload: payload["findings"].extend(
            deepcopy(payload["findings"][0]) | {"id": f"overflow-{index}"} for index in range(20)
        ),
        lambda payload: payload["findings"][0].pop("location"),
        lambda payload: payload["findings"][0].update(quote=""),
        lambda payload: payload["findings"][0].update(clarification=""),
    ],
    ids=[
        "duplicate-finding-id",
        "more-than-20-findings",
        "missing-location",
        "empty-quote",
        "empty-clarification",
    ],
)
def test_invalid_finding_contract_is_rejected_without_correction(
    tmp_path: Path,
    sessions: sessionmaker[Session],
    mutate: Any,
) -> None:
    payload = success_payload()
    job_id = seed_running_job(sessions, payload)
    mutate(payload)
    workspace = prepare_workspace(tmp_path, payload)

    with pytest.raises(ResultSchemaError):
        receiver(sessions).receive(job_id, workspace, execution())

    with sessions() as session:
        stored = ReviewJobRepository(session).require(job_id)
        assert stored.raw_result is None
        assert stored.status is ReviewJobStatus.RUNNING


@pytest.mark.parametrize(
    "field",
    ["returned_findings", "high", "verified_candidates"],
)
def test_inconsistent_summary_is_rejected_without_rewriting_core_result(
    tmp_path: Path,
    sessions: sessionmaker[Session],
    field: str,
) -> None:
    payload = success_payload()
    job_id = seed_running_job(sessions, payload)
    payload["summary"][field] = 0
    workspace = prepare_workspace(tmp_path, payload)

    with pytest.raises(ResultSchemaError):
        receiver(sessions).receive(job_id, workspace, execution())

    with sessions() as session:
        stored = ReviewJobRepository(session).require(job_id)
        assert stored.raw_result is None
        assert stored.status is ReviewJobStatus.RUNNING


def test_unknown_schema_major_has_specific_error(
    tmp_path: Path, sessions: sessionmaker[Session]
) -> None:
    payload = success_payload()
    job_id = seed_running_job(sessions, payload)
    payload["schema_version"] = "2.0"
    workspace = prepare_workspace(tmp_path, payload)

    with pytest.raises(IncompatibleSchemaVersionError, match="major 2"):
        receiver(sessions).receive(job_id, workspace, execution())


def test_run_id_process_and_workspace_mismatches_are_rejected(
    tmp_path: Path, sessions: sessionmaker[Session]
) -> None:
    payload = success_payload()
    job_id = seed_running_job(sessions, payload)
    workspace = prepare_workspace(tmp_path, payload)

    changed = deepcopy(payload)
    changed["run_id"] = "other-result"
    workspace.resolve("output/result.json").write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ResultIdentityMismatchError, match="result run_id"):
        receiver(sessions).receive(job_id, workspace, execution())

    with pytest.raises(ResultIdentityMismatchError, match="PID"):
        receiver(sessions).receive(job_id, workspace, execution(pid=9999))

    other_workspace = RunWorkspaceManager(tmp_path / "other-runs").prepare("other-workspace")
    with pytest.raises(ResultIdentityMismatchError, match="workspace run_id"):
        receiver(sessions).receive(job_id, other_workspace, execution())


def test_exit_zero_with_failed_result_is_rejected(
    tmp_path: Path, sessions: sessionmaker[Session]
) -> None:
    payload = success_payload()
    job_id = seed_running_job(sessions, payload)
    failed_payload = {
        "schema_version": "1.0",
        "run_id": payload["run_id"],
        "status": "failed",
        "error": {
            "code": "INTERNAL_ERROR",
            "stage": "pipeline",
            "message": "failed",
            "retriable": False,
        },
    }
    workspace = prepare_workspace(tmp_path, failed_payload)

    with pytest.raises(ResultSchemaError, match="exit code 0"):
        receiver(sessions).receive(job_id, workspace, execution())


def test_cancelled_job_does_not_accept_late_valid_result(
    tmp_path: Path, sessions: sessionmaker[Session]
) -> None:
    payload = success_payload()
    job_id = seed_running_job(sessions, payload)
    workspace = prepare_workspace(tmp_path, payload)
    with sessions.begin() as session:
        ReviewJobRepository(session).cancel(
            job_id,
            at=FINISHED_AT,
            failure=ReviewJobFailure(
                error_code="ANALYSIS_CANCELLED",
                user_message="Проверка отменена.",
            ),
        )

    with pytest.raises(InvalidReviewJobTransition):
        receiver(sessions).receive(
            job_id,
            workspace,
            execution(),
        )

    with sessions() as session:
        stored = ReviewJobRepository(session).require(job_id)
        assert stored.status is ReviewJobStatus.CANCELLED
        assert stored.raw_result is None


def test_receiver_rejects_unusable_schema(sessions: sessionmaker[Session], tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="schema"):
        ReviewResultReceiver(sessions, schema_path=tmp_path / "missing.json")
