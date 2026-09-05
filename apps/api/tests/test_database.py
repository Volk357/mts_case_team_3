import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, func, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from docreview_api.db import Base, create_database_engine, create_session_factory
from docreview_api.db.models import (
    CompanyModel,
    DocumentModel,
    FindingFeedbackModel,
    FindingModel,
    ReviewJobModel,
    ReviewPackReferenceModel,
    UserModel,
)
from docreview_api.models import (
    InvalidReviewJobTransition,
    ReviewJobStatus,
    prepare_review_result_snapshot,
)
from docreview_api.repositories import (
    CompanyRepository,
    DocumentRepository,
    EntityNotFoundError,
    FindingFeedbackRepository,
    FindingRepository,
    ReviewJobRepository,
    ReviewPackReferenceRepository,
    ReviewResultConflictError,
    TenantBoundaryError,
    UserRepository,
    complete_review_job,
)

API_DIRECTORY = Path(__file__).resolve().parents[1]
REPOSITORY_DIRECTORY = API_DIRECTORY.parents[1]
SUCCESS_EXAMPLE = REPOSITORY_DIRECTORY / "contracts" / "examples" / "success.json"
FAILURE_EXAMPLE = REPOSITORY_DIRECTORY / "contracts" / "examples" / "failure.json"
STARTED_AT = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)


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


def success_payload(run_id: str = "review-123") -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(SUCCESS_EXAMPLE.read_text(encoding="utf-8"))
    payload["run_id"] = run_id
    return payload


def seed_job(
    sessions: sessionmaker[Session],
    *,
    run_id: str = "review-123",
    company_slug: str = "mts",
) -> tuple[CompanyModel, UserModel, DocumentModel, ReviewPackReferenceModel, ReviewJobModel]:
    with sessions.begin() as session:
        company = CompanyRepository(session).add(
            CompanyModel(slug=company_slug, display_name="Test company")
        )
        user = UserRepository(session).add(
            UserModel(
                company_id=company.id,
                external_subject="analyst-1",
                display_name="Analyst",
                email=None,
            )
        )
        document = DocumentRepository(session).add(
            DocumentModel(
                company_id=company.id,
                uploaded_by_user_id=user.id,
                original_filename="requirements.pdf",
                media_type="application/pdf",
                size_bytes=100,
                sha256="0" * 64,
                storage_key=f"{company_slug}/document.pdf",
            )
        )
        review_pack = ReviewPackReferenceRepository(session).add(
            ReviewPackReferenceModel(
                company_id=company.id,
                pack_key="mts-data-mart",
                version="1.0",
                display_name="Data mart",
                locator="review-packs/mts-data-mart/1.0",
            )
        )
        job = ReviewJobRepository(session).add(
            ReviewJobModel(
                run_id=run_id,
                company_id=company.id,
                document_id=document.id,
                review_pack_reference_id=review_pack.id,
                requested_by_user_id=user.id,
                queued_at=STARTED_AT,
                created_at=STARTED_AT,
                updated_at=STARTED_AT,
            )
        )
    return company, user, document, review_pack, job


def start_job(sessions: sessionmaker[Session], job_id: Any) -> None:
    with sessions.begin() as session:
        ReviewJobRepository(session).start(job_id, at=STARTED_AT + timedelta(seconds=1))


def snapshot_for(run_id: str = "review-123") -> Any:
    return prepare_review_result_snapshot(
        success_payload(run_id),
        expected_document_sha256="0" * 64,
    )


def test_migration_upgrades_empty_database_and_downgrades_one_step(database_url: str) -> None:
    configuration = Config(str(API_DIRECTORY / "alembic.ini"))
    configuration.set_main_option("sqlalchemy.url", database_url)

    command.upgrade(configuration, "head")
    migrated_engine = create_database_engine(database_url)
    database_inspector = inspect(migrated_engine)
    expected_tables = {
        "companies",
        "users",
        "documents",
        "review_pack_references",
        "review_jobs",
        "findings",
        "finding_feedback",
    }
    assert expected_tables <= set(database_inspector.get_table_names())
    assert {index["name"] for index in database_inspector.get_indexes("review_jobs")} >= {
        "ix_review_jobs_status",
        "ix_review_jobs_document_id",
        "ix_review_jobs_created_at",
    }
    assert "idempotency_key" in {
        column["name"] for column in database_inspector.get_columns("review_jobs")
    }
    assert "process_pid" in {
        column["name"] for column in database_inspector.get_columns("review_jobs")
    }
    assert "document_type" in {
        column["name"] for column in database_inspector.get_columns("review_pack_references")
    }
    assert "uq_review_jobs_company_idempotency" in {
        constraint["name"]
        for constraint in database_inspector.get_unique_constraints("review_jobs")
    }
    migrated_engine.dispose()
    command.check(configuration)

    command.downgrade(configuration, "base")
    downgraded_engine = create_database_engine(database_url)
    assert expected_tables.isdisjoint(inspect(downgraded_engine).get_table_names())
    downgraded_engine.dispose()


def test_entities_are_created_and_read_through_repositories(
    sessions: sessionmaker[Session],
) -> None:
    company, user, document, review_pack, job = seed_job(sessions)

    with sessions() as session:
        assert CompanyRepository(session).require(company.id).slug == "mts"
        assert UserRepository(session).require(user.id).company_id == company.id
        assert DocumentRepository(session).require(document.id).sha256 == "0" * 64
        assert ReviewPackReferenceRepository(session).require(review_pack.id).version == "1.0"
        assert ReviewJobRepository(session).require(job.id).status is ReviewJobStatus.QUEUED


def test_start_persists_process_pid_and_start_time(sessions: sessionmaker[Session]) -> None:
    *_, job = seed_job(sessions)
    started_at = STARTED_AT + timedelta(seconds=1)

    with sessions.begin() as session:
        ReviewJobRepository(session).start(job.id, at=started_at, process_pid=4242)

    with sessions() as restarted_session:
        stored = ReviewJobRepository(restarted_session).require(job.id)
        assert stored.status is ReviewJobStatus.RUNNING
        assert stored.process_pid == 4242
        assert stored.started_at.replace(tzinfo=UTC) == started_at


def test_completion_atomically_persists_raw_result_versions_and_findings(
    sessions: sessionmaker[Session],
) -> None:
    _, _, _, _, job = seed_job(sessions)
    start_job(sessions, job.id)
    snapshot = snapshot_for()

    complete_review_job(
        sessions,
        job.id,
        snapshot,
        at=STARTED_AT + timedelta(seconds=2),
    )

    with sessions() as restarted_backend_session:
        stored = ReviewJobRepository(restarted_backend_session).require(job.id)
        findings = FindingRepository(restarted_backend_session).list_for_job(job.id)
        assert stored.status is ReviewJobStatus.COMPLETED
        assert stored.raw_result == snapshot.raw_result
        assert stored.schema_version == "1.0"
        assert stored.engine_version == "0.1.0"
        assert stored.result_review_pack_id == "mts-data-mart"
        assert stored.result_review_pack_version == "1.0"
        assert stored.model_name == "qwen"
        assert stored.prompt_versions == {"data_logic": "3", "completeness": "2"}
        assert stored.completed_at is not None
        assert [finding.core_finding_id for finding in findings] == [
            "finding-001",
            "finding-002",
        ]


def test_reprocessing_identical_result_does_not_duplicate_findings(
    sessions: sessionmaker[Session],
) -> None:
    _, _, _, _, job = seed_job(sessions)
    start_job(sessions, job.id)
    snapshot = snapshot_for()
    completed_at = STARTED_AT + timedelta(seconds=2)

    complete_review_job(sessions, job.id, snapshot, at=completed_at)
    complete_review_job(sessions, job.id, snapshot, at=completed_at + timedelta(seconds=1))

    with sessions() as session:
        count = session.scalar(
            select(func.count())
            .select_from(FindingModel)
            .where(FindingModel.review_job_id == job.id)
        )
        assert count == 2


def test_failed_completion_rolls_back_job_and_all_findings(
    sessions: sessionmaker[Session],
) -> None:
    _, _, _, _, job = seed_job(sessions, run_id="atomic-failure")
    start_job(sessions, job.id)
    payload = success_payload("atomic-failure")
    payload["findings"][1]["id"] = payload["findings"][0]["id"]
    snapshot = prepare_review_result_snapshot(payload, expected_document_sha256="0" * 64)

    with pytest.raises(IntegrityError):
        complete_review_job(
            sessions,
            job.id,
            snapshot,
            at=STARTED_AT + timedelta(seconds=2),
        )

    with sessions() as session:
        stored = ReviewJobRepository(session).require(job.id)
        assert stored.status is ReviewJobStatus.RUNNING
        assert stored.raw_result is None
        assert FindingRepository(session).list_for_job(job.id) == []


def test_feedback_upsert_does_not_change_source_finding(
    sessions: sessionmaker[Session],
) -> None:
    company, user, _, _, job = seed_job(sessions)
    start_job(sessions, job.id)
    complete_review_job(
        sessions,
        job.id,
        snapshot_for(),
        at=STARTED_AT + timedelta(seconds=2),
    )

    with sessions.begin() as session:
        finding = FindingRepository(session).list_for_job(job.id)[0]
        original_problem = finding.problem
        repository = FindingFeedbackRepository(session)
        first = repository.upsert(
            company_id=company.id,
            finding_id=finding.id,
            submitted_by_user_id=user.id,
            actor_key="analyst-session",
            decision="accepted",
            comment=None,
        )
        feedback_id = first.id
        updated = repository.upsert(
            company_id=company.id,
            finding_id=finding.id,
            submitted_by_user_id=user.id,
            actor_key="analyst-session",
            decision="false_positive",
            comment="Checked against source",
        )
        assert updated.id == feedback_id
        assert finding.problem == original_problem

    with sessions() as session:
        feedback_count = session.scalar(select(func.count()).select_from(FindingFeedbackModel))
        assert feedback_count == 1
        assert FindingRepository(session).list_for_job(job.id)[0].problem == original_problem


def test_repository_rejects_cross_company_review_job(sessions: sessionmaker[Session]) -> None:
    company, user, document, _, _ = seed_job(sessions)
    _, _, _, foreign_pack, _ = seed_job(
        sessions,
        run_id="foreign-seed",
        company_slug="foreign",
    )

    with sessions.begin() as session, pytest.raises(TenantBoundaryError):
        ReviewJobRepository(session).add(
            ReviewJobModel(
                run_id="cross-company",
                company_id=company.id,
                document_id=document.id,
                review_pack_reference_id=foreign_pack.id,
                requested_by_user_id=user.id,
                queued_at=STARTED_AT,
                created_at=STARTED_AT,
                updated_at=STARTED_AT,
            )
        )


def test_repository_require_and_lock_reject_unknown_ids(
    sessions: sessionmaker[Session],
) -> None:
    with sessions() as session:
        with pytest.raises(EntityNotFoundError):
            CompanyRepository(session).require(uuid4())
        with pytest.raises(EntityNotFoundError):
            ReviewJobRepository(session).start(uuid4(), at=STARTED_AT)


def test_document_repository_enforces_user_tenant(sessions: sessionmaker[Session]) -> None:
    company, _, _, _, _ = seed_job(sessions)
    _, foreign_user, _, _, _ = seed_job(
        sessions,
        run_id="foreign-document-user",
        company_slug="foreign-document",
    )

    with sessions.begin() as session, pytest.raises(TenantBoundaryError):
        DocumentRepository(session).add(
            DocumentModel(
                company_id=company.id,
                uploaded_by_user_id=foreign_user.id,
                original_filename="cross-tenant.pdf",
                media_type="application/pdf",
                size_bytes=1,
                sha256="1" * 64,
                storage_key="cross-tenant/document.pdf",
            )
        )


def test_feedback_repository_rejects_missing_and_cross_tenant_entities(
    sessions: sessionmaker[Session],
) -> None:
    company, _, _, _, job = seed_job(sessions)
    start_job(sessions, job.id)
    complete_review_job(
        sessions,
        job.id,
        snapshot_for(),
        at=STARTED_AT + timedelta(seconds=2),
    )
    foreign_company, foreign_user, _, _, _ = seed_job(
        sessions,
        run_id="foreign-feedback",
        company_slug="foreign-feedback",
    )

    with sessions.begin() as session:
        repository = FindingFeedbackRepository(session)
        finding = FindingRepository(session).list_for_job(job.id)[0]
        with pytest.raises(EntityNotFoundError):
            repository.upsert(
                company_id=company.id,
                finding_id=uuid4(),
                actor_key="missing",
                decision="accepted",
                comment=None,
            )
        with pytest.raises(TenantBoundaryError):
            repository.upsert(
                company_id=foreign_company.id,
                finding_id=finding.id,
                actor_key="wrong-company",
                decision="accepted",
                comment=None,
            )
        with pytest.raises(TenantBoundaryError):
            repository.upsert(
                company_id=company.id,
                finding_id=finding.id,
                submitted_by_user_id=foreign_user.id,
                actor_key="wrong-user",
                decision="accepted",
                comment=None,
            )


def test_completion_rejects_failed_mismatched_and_changed_results(
    sessions: sessionmaker[Session],
) -> None:
    _, _, _, _, job = seed_job(sessions)
    start_job(sessions, job.id)
    failure_payload: dict[str, Any] = json.loads(FAILURE_EXAMPLE.read_text(encoding="utf-8"))
    failed_snapshot = prepare_review_result_snapshot(
        failure_payload,
        expected_document_sha256="0" * 64,
    )
    with pytest.raises(ReviewResultConflictError, match="completed ReviewResult"):
        complete_review_job(sessions, job.id, failed_snapshot, at=STARTED_AT + timedelta(seconds=2))

    wrong_run_snapshot = snapshot_for("another-run")
    with pytest.raises(ReviewResultConflictError, match="run_id"):
        complete_review_job(
            sessions,
            job.id,
            wrong_run_snapshot,
            at=STARTED_AT + timedelta(seconds=2),
        )

    payload = success_payload()
    payload["review_pack"]["version"] = "2.0"
    wrong_pack_snapshot = prepare_review_result_snapshot(
        payload,
        expected_document_sha256="0" * 64,
    )
    with pytest.raises(ReviewResultConflictError, match="Review Pack"):
        complete_review_job(
            sessions,
            job.id,
            wrong_pack_snapshot,
            at=STARTED_AT + timedelta(seconds=2),
        )

    complete_review_job(
        sessions,
        job.id,
        snapshot_for(),
        at=STARTED_AT + timedelta(seconds=2),
    )
    changed_payload = success_payload()
    changed_payload["future_field"] = "different"
    changed_snapshot = prepare_review_result_snapshot(
        changed_payload,
        expected_document_sha256="0" * 64,
    )
    with pytest.raises(ReviewResultConflictError, match="different result"):
        complete_review_job(
            sessions,
            job.id,
            changed_snapshot,
            at=STARTED_AT + timedelta(seconds=3),
        )


def test_terminal_job_cannot_be_started_again(sessions: sessionmaker[Session]) -> None:
    _, _, _, _, job = seed_job(sessions)
    start_job(sessions, job.id)
    complete_review_job(
        sessions,
        job.id,
        snapshot_for(),
        at=STARTED_AT + timedelta(seconds=2),
    )

    with sessions.begin() as session, pytest.raises(InvalidReviewJobTransition):
        ReviewJobRepository(session).start(job.id, at=STARTED_AT + timedelta(seconds=3))


def test_finding_and_feedback_direct_repositories_enforce_tenant_boundary(
    sessions: sessionmaker[Session],
) -> None:
    company, user, _, _, job = seed_job(sessions)
    foreign_company, foreign_user, _, _, _ = seed_job(
        sessions,
        run_id="foreign-direct-repositories",
        company_slug="foreign-direct",
    )

    with sessions.begin() as session:
        finding_repository = FindingRepository(session)
        finding = finding_repository.add(
            FindingModel(
                company_id=company.id,
                review_job_id=job.id,
                core_finding_id="manual-finding",
                ordinal=0,
                defect_id="MANUAL_TEST",
                severity="low",
                confidence=0.5,
                location={"page": 1, "section_path": ["Section"], "block_id": "block-1"},
                quote="Source quote",
                problem="Possible problem",
                clarification="Clarify requirement",
                detected_by=["test"],
            )
        )
        feedback = FindingFeedbackRepository(session).add(
            FindingFeedbackModel(
                company_id=company.id,
                finding_id=finding.id,
                submitted_by_user_id=user.id,
                actor_key="direct-actor",
                decision="accepted",
                comment=None,
            )
        )
        assert finding_repository.require(finding.id).core_finding_id == "manual-finding"
        assert FindingFeedbackRepository(session).require(feedback.id).decision == "accepted"

        with pytest.raises(EntityNotFoundError):
            finding_repository.add(
                FindingModel(
                    company_id=company.id,
                    review_job_id=uuid4(),
                    core_finding_id="missing-job",
                    ordinal=1,
                    defect_id="MANUAL_TEST",
                    severity="low",
                    confidence=0.5,
                    location={},
                    quote="quote",
                    problem="problem",
                    clarification="clarification",
                    detected_by=["test"],
                )
            )
        with pytest.raises(TenantBoundaryError):
            FindingFeedbackRepository(session).add(
                FindingFeedbackModel(
                    company_id=foreign_company.id,
                    finding_id=finding.id,
                    submitted_by_user_id=foreign_user.id,
                    actor_key="wrong-company-direct",
                    decision="accepted",
                    comment=None,
                )
            )


def test_document_repository_rejects_missing_user(sessions: sessionmaker[Session]) -> None:
    company, _, _, _, _ = seed_job(sessions)

    with sessions.begin() as session, pytest.raises(EntityNotFoundError):
        DocumentRepository(session).add(
            DocumentModel(
                company_id=company.id,
                uploaded_by_user_id=uuid4(),
                original_filename="missing-user.pdf",
                media_type="application/pdf",
                size_bytes=1,
                sha256="2" * 64,
                storage_key="missing-user/document.pdf",
            )
        )
