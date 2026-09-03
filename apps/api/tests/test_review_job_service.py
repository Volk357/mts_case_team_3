from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from docreview_api.db import Base, create_database_engine, create_session_factory
from docreview_api.db.models import (
    CompanyModel,
    DocumentModel,
    ReviewJobModel,
    ReviewPackReferenceModel,
    UserModel,
)
from docreview_api.models import ReviewJobFailure, ReviewJobStatus
from docreview_api.repositories import ReviewJobRepository
from docreview_api.services import (
    IdempotencyConflictError,
    ReviewJobCreationError,
    ReviewJobNotRetryableError,
    ReviewJobResourceUnavailableError,
    ReviewJobService,
)

NOW = datetime(2026, 9, 3, 15, 0, tzinfo=UTC)


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    database_engine = create_database_engine(f"sqlite:///{(tmp_path / 'jobs.db').as_posix()}")
    Base.metadata.create_all(database_engine)
    try:
        yield database_engine
    finally:
        database_engine.dispose()


@pytest.fixture
def sessions(engine: Engine) -> sessionmaker[Session]:
    return create_session_factory(engine)


def seed_resources(
    sessions: sessionmaker[Session], *, slug: str = "company"
) -> tuple[UUID, UUID, UUID, UUID]:
    with sessions.begin() as session:
        company = CompanyModel(slug=slug, display_name=slug)
        session.add(company)
        session.flush()
        user = UserModel(
            company_id=company.id,
            external_subject=f"{slug}-analyst",
            display_name="Analyst",
        )
        document = DocumentModel(
            company_id=company.id,
            original_filename="requirements.pdf",
            media_type="application/pdf",
            size_bytes=10,
            sha256="a" * 64,
            storage_key=f"{slug}/document.pdf",
        )
        review_pack = ReviewPackReferenceModel(
            company_id=company.id,
            pack_key="requirements",
            version="1.0",
            display_name="Requirements",
            locator=f"review-packs/{slug}/requirements/1.0",
        )
        session.add_all([user, document, review_pack])
        session.flush()
        return company.id, user.id, document.id, review_pack.id


def create_job(
    session: Session,
    resources: tuple[UUID, UUID, UUID, UUID],
    *,
    key: str = "upload-screen-submit-1",
    run_id: str = "review-created-by-service",
) -> ReviewJobModel:
    company_id, user_id, document_id, review_pack_id = resources
    result = ReviewJobService(
        session,
        clock=lambda: NOW,
        run_id_factory=lambda: run_id,
    ).create(
        company_id=company_id,
        document_id=document_id,
        review_pack_reference_id=review_pack_id,
        requested_by_user_id=user_id,
        idempotency_key=key,
    )
    assert result.created
    return result.job


def test_create_persists_queued_job_with_unique_run_id(
    sessions: sessionmaker[Session],
) -> None:
    resources = seed_resources(sessions)
    with sessions.begin() as session:
        first = create_job(session, resources, key="submit-1", run_id="review-one")
        second = create_job(session, resources, key="submit-2", run_id="review-two")

        assert first.run_id != second.run_id
        assert first.status is ReviewJobStatus.QUEUED
        assert first.queued_at == NOW
        assert first.raw_result is None

    with sessions() as restarted_session:
        stored = restarted_session.get(ReviewJobModel, first.id)
        assert stored is not None
        assert stored.idempotency_key == "submit-1"
        assert stored.status is ReviewJobStatus.QUEUED


def test_same_idempotency_key_returns_original_job_once(
    sessions: sessionmaker[Session],
) -> None:
    resources = seed_resources(sessions)
    with sessions.begin() as session:
        original = create_job(session, resources)
        company_id, user_id, document_id, review_pack_id = resources
        duplicate = ReviewJobService(
            session,
            clock=lambda: NOW,
            run_id_factory=lambda: "must-not-be-used",
        ).create(
            company_id=company_id,
            document_id=document_id,
            review_pack_reference_id=review_pack_id,
            requested_by_user_id=user_id,
            idempotency_key="upload-screen-submit-1",
        )

        assert not duplicate.created
        assert duplicate.job.id == original.id
        assert duplicate.job.run_id == original.run_id
        assert session.scalar(select(func.count()).select_from(ReviewJobModel)) == 1


def test_reusing_idempotency_key_for_different_request_is_rejected(
    sessions: sessionmaker[Session],
) -> None:
    resources = seed_resources(sessions)
    with sessions.begin() as session:
        create_job(session, resources)
        company_id, user_id, _, review_pack_id = resources
        other_document = DocumentModel(
            company_id=company_id,
            original_filename="other.docx",
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            size_bytes=20,
            sha256="b" * 64,
            storage_key="company/other.docx",
        )
        session.add(other_document)
        session.flush()

        with pytest.raises(IdempotencyConflictError):
            ReviewJobService(session).create(
                company_id=company_id,
                document_id=other_document.id,
                review_pack_reference_id=review_pack_id,
                requested_by_user_id=user_id,
                idempotency_key="upload-screen-submit-1",
            )

        assert session.scalar(select(func.count()).select_from(ReviewJobModel)) == 1


@pytest.mark.parametrize("resource", ["deleted_document", "inactive_pack", "inactive_user"])
def test_unavailable_resources_are_rejected(sessions: sessionmaker[Session], resource: str) -> None:
    resources = seed_resources(sessions)
    company_id, user_id, document_id, review_pack_id = resources
    with sessions.begin() as session:
        if resource == "deleted_document":
            document = session.get(DocumentModel, document_id)
            assert document is not None
            document.deleted_at = NOW
        elif resource == "inactive_pack":
            review_pack = session.get(ReviewPackReferenceModel, review_pack_id)
            assert review_pack is not None
            review_pack.is_active = False
        else:
            user = session.get(UserModel, user_id)
            assert user is not None
            user.is_active = False

        with pytest.raises(ReviewJobResourceUnavailableError):
            ReviewJobService(session).create(
                company_id=company_id,
                document_id=document_id,
                review_pack_reference_id=review_pack_id,
                requested_by_user_id=user_id,
                idempotency_key="rejected-submit",
            )


def test_cross_company_document_and_pack_are_not_available(
    sessions: sessionmaker[Session],
) -> None:
    own = seed_resources(sessions, slug="own")
    foreign = seed_resources(sessions, slug="foreign")
    company_id, user_id, document_id, _ = own
    foreign_pack_id = foreign[3]

    with sessions.begin() as session, pytest.raises(ReviewJobResourceUnavailableError):
        ReviewJobService(session).create(
            company_id=company_id,
            document_id=document_id,
            review_pack_reference_id=foreign_pack_id,
            requested_by_user_id=user_id,
            idempotency_key="cross-tenant-submit",
        )


@pytest.mark.parametrize("key", ["", "   ", "line\nbreak", "x" * 256])
def test_invalid_idempotency_keys_are_rejected(sessions: sessionmaker[Session], key: str) -> None:
    resources = seed_resources(sessions)
    company_id, user_id, document_id, review_pack_id = resources

    with sessions.begin() as session, pytest.raises(ReviewJobCreationError):
        ReviewJobService(session).create(
            company_id=company_id,
            document_id=document_id,
            review_pack_reference_id=review_pack_id,
            requested_by_user_id=user_id,
            idempotency_key=key,
        )


def test_missing_document_or_pack_is_rejected(sessions: sessionmaker[Session]) -> None:
    company_id, user_id, document_id, review_pack_id = seed_resources(sessions)

    with sessions.begin() as session:
        service = ReviewJobService(session)
        with pytest.raises(ReviewJobResourceUnavailableError, match="document"):
            service.create(
                company_id=company_id,
                document_id=uuid4(),
                review_pack_reference_id=review_pack_id,
                requested_by_user_id=user_id,
                idempotency_key="missing-document",
            )
        with pytest.raises(ReviewJobResourceUnavailableError, match="Review Pack"):
            service.create(
                company_id=company_id,
                document_id=document_id,
                review_pack_reference_id=uuid4(),
                requested_by_user_id=user_id,
                idempotency_key="missing-pack",
            )


def test_user_retry_creates_new_idempotent_job_and_preserves_original(
    sessions: sessionmaker[Session],
) -> None:
    resources = seed_resources(sessions)
    with sessions.begin() as session:
        original = create_job(session, resources, run_id="review-original")
        ReviewJobRepository(session).start(original.id, at=NOW + timedelta(seconds=1))
        ReviewJobRepository(session).fail(
            original.id,
            at=NOW + timedelta(seconds=2),
            failure=ReviewJobFailure(
                error_code="MODEL_UNAVAILABLE",
                user_message="Модель временно недоступна.",
                retriable=True,
            ),
        )

        retry_service = ReviewJobService(
            session,
            clock=lambda: NOW + timedelta(seconds=3),
            run_id_factory=lambda: "review-retry",
        )
        company_id, user_id, _, _ = resources
        retry = retry_service.retry(
            original.id,
            company_id=company_id,
            requested_by_user_id=user_id,
            idempotency_key="retry-submit-1",
        )
        duplicate = retry_service.retry(
            original.id,
            company_id=company_id,
            requested_by_user_id=user_id,
            idempotency_key="retry-submit-1",
        )

        assert retry.created
        assert not duplicate.created
        assert retry.job.id == duplicate.job.id
        assert retry.job.run_id == "review-retry"
        assert retry.job.run_id != original.run_id
        assert retry.job.retry_of_job_id == original.id
        assert retry.job.status is ReviewJobStatus.QUEUED
        assert original.status is ReviewJobStatus.FAILED
        assert session.scalar(select(func.count()).select_from(ReviewJobModel)) == 2


def test_running_job_cannot_be_retried(sessions: sessionmaker[Session]) -> None:
    resources = seed_resources(sessions)
    with sessions.begin() as session:
        original = create_job(session, resources)
        company_id, user_id, _, _ = resources

        with pytest.raises(ReviewJobNotRetryableError):
            ReviewJobService(session).retry(
                original.id,
                company_id=company_id,
                requested_by_user_id=user_id,
                idempotency_key="premature-retry",
            )
