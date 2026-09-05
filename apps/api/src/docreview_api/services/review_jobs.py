"""Creation of durable, tenant-scoped review jobs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from docreview_api.db.models import (
    CompanyModel,
    DocumentModel,
    ReviewJobModel,
    ReviewPackReferenceModel,
    UserModel,
)
from docreview_api.models.review_job_state import TERMINAL_STATUSES, ReviewJobStatus
from docreview_api.repositories.database import ReviewJobRepository

MAX_IDEMPOTENCY_KEY_LENGTH = 255
MAX_RUN_ID_LENGTH = 128


class ReviewJobCreationError(ValueError):
    """Base error for a rejected review job request."""


class ReviewJobResourceUnavailableError(ReviewJobCreationError):
    """A requested resource is missing, inactive, deleted, or outside the tenant."""


class ReviewJobDocumentUnavailableError(ReviewJobResourceUnavailableError):
    """The requested document cannot be used by this tenant."""


class ReviewJobPackUnavailableError(ReviewJobResourceUnavailableError):
    """The requested Review Pack cannot be used by this tenant."""


class IdempotencyConflictError(ReviewJobCreationError):
    """An idempotency key was already used for different request parameters."""


class ReviewJobNotRetryableError(ReviewJobCreationError):
    """A user retry referenced a job that has not reached a terminal state."""


@dataclass(frozen=True, slots=True)
class ReviewJobCreationResult:
    """The persisted job and whether this call created it."""

    job: ReviewJobModel
    created: bool


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _new_run_id() -> str:
    return f"review-{uuid4().hex}"


class ReviewJobService:
    """Validate references and enqueue one idempotent review job."""

    def __init__(
        self,
        session: Session,
        *,
        clock: Callable[[], datetime] = _utc_now,
        run_id_factory: Callable[[], str] = _new_run_id,
    ) -> None:
        self._session = session
        self._repository = ReviewJobRepository(session)
        self._clock = clock
        self._run_id_factory = run_id_factory

    def create(
        self,
        *,
        company_id: UUID,
        document_id: UUID,
        review_pack_reference_id: UUID,
        idempotency_key: str,
        requested_by_user_id: UUID | None = None,
    ) -> ReviewJobCreationResult:
        """Create a queued job or return the matching prior idempotent request.

        Transaction ownership remains with the caller. A database uniqueness
        constraint closes the race between concurrent requests using the same key.
        """

        return self._create(
            company_id=company_id,
            document_id=document_id,
            review_pack_reference_id=review_pack_reference_id,
            idempotency_key=idempotency_key,
            requested_by_user_id=requested_by_user_id,
            retry_of_job_id=None,
        )

    def retry(
        self,
        previous_job_id: UUID,
        *,
        company_id: UUID,
        idempotency_key: str,
        requested_by_user_id: UUID | None = None,
    ) -> ReviewJobCreationResult:
        """Create a new user-requested run linked to one immutable terminal job."""

        previous = self._session.get(ReviewJobModel, previous_job_id)
        if previous is None or previous.company_id != company_id:
            raise ReviewJobResourceUnavailableError("previous review job is unavailable")
        if previous.status not in TERMINAL_STATUSES:
            raise ReviewJobNotRetryableError("only a terminal review job can be retried")
        return self._create(
            company_id=company_id,
            document_id=previous.document_id,
            review_pack_reference_id=previous.review_pack_reference_id,
            idempotency_key=idempotency_key,
            requested_by_user_id=requested_by_user_id,
            retry_of_job_id=previous.id,
        )

    def _create(
        self,
        *,
        company_id: UUID,
        document_id: UUID,
        review_pack_reference_id: UUID,
        idempotency_key: str,
        requested_by_user_id: UUID | None,
        retry_of_job_id: UUID | None,
    ) -> ReviewJobCreationResult:
        key = self._validate_idempotency_key(idempotency_key)
        existing = self._find_by_idempotency_key(company_id, key)
        if existing is not None:
            self._ensure_same_request(
                existing,
                document_id=document_id,
                review_pack_reference_id=review_pack_reference_id,
                requested_by_user_id=requested_by_user_id,
                retry_of_job_id=retry_of_job_id,
            )
            return ReviewJobCreationResult(job=existing, created=False)

        self._validate_resources(
            company_id=company_id,
            document_id=document_id,
            review_pack_reference_id=review_pack_reference_id,
            requested_by_user_id=requested_by_user_id,
            retry_of_job_id=retry_of_job_id,
        )
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() != UTC.utcoffset(now):
            raise ReviewJobCreationError("clock must return a timezone-aware UTC datetime")
        run_id = self._run_id_factory()
        if not run_id or len(run_id) > MAX_RUN_ID_LENGTH:
            raise ReviewJobCreationError("run_id factory returned an invalid identifier")

        job = ReviewJobModel(
            run_id=run_id,
            idempotency_key=key,
            company_id=company_id,
            document_id=document_id,
            review_pack_reference_id=review_pack_reference_id,
            requested_by_user_id=requested_by_user_id,
            retry_of_job_id=retry_of_job_id,
            status=ReviewJobStatus.QUEUED,
            queued_at=now,
            created_at=now,
            updated_at=now,
        )
        try:
            # Keep the caller's transaction usable if a concurrent insert wins.
            with self._session.begin_nested():
                self._repository.add(job)
        except IntegrityError:
            existing = self._find_by_idempotency_key(company_id, key)
            if existing is None:
                raise
            self._ensure_same_request(
                existing,
                document_id=document_id,
                review_pack_reference_id=review_pack_reference_id,
                requested_by_user_id=requested_by_user_id,
                retry_of_job_id=retry_of_job_id,
            )
            return ReviewJobCreationResult(job=existing, created=False)
        return ReviewJobCreationResult(job=job, created=True)

    def _find_by_idempotency_key(
        self, company_id: UUID, idempotency_key: str
    ) -> ReviewJobModel | None:
        statement = select(ReviewJobModel).where(
            ReviewJobModel.company_id == company_id,
            ReviewJobModel.idempotency_key == idempotency_key,
        )
        return self._session.scalar(statement)

    def _validate_resources(
        self,
        *,
        company_id: UUID,
        document_id: UUID,
        review_pack_reference_id: UUID,
        requested_by_user_id: UUID | None,
        retry_of_job_id: UUID | None,
    ) -> None:
        company = self._session.get(CompanyModel, company_id)
        if company is None or not company.is_active:
            raise ReviewJobResourceUnavailableError("company is unavailable")

        # Строка документа блокируется на время проверки его пригодности:
        # иначе удаление файла и постановка задачи расходятся по разным
        # транзакциям, обе видят допустимое состояние, и в очередь попадает
        # задача на документ, исходника которого уже нет.
        document = self._session.get(DocumentModel, document_id, with_for_update=True)
        if document is None or document.company_id != company_id or document.deleted_at is not None:
            raise ReviewJobDocumentUnavailableError("document is unavailable")

        review_pack = self._session.get(ReviewPackReferenceModel, review_pack_reference_id)
        if review_pack is None or review_pack.company_id != company_id or not review_pack.is_active:
            raise ReviewJobPackUnavailableError("Review Pack is unavailable")

        if requested_by_user_id is not None:
            user = self._session.get(UserModel, requested_by_user_id)
            if user is None or user.company_id != company_id or not user.is_active:
                raise ReviewJobResourceUnavailableError("requesting user is unavailable")

        if retry_of_job_id is not None:
            previous = self._session.get(ReviewJobModel, retry_of_job_id)
            if previous is None or previous.company_id != company_id:
                raise ReviewJobResourceUnavailableError("previous review job is unavailable")

    @staticmethod
    def _validate_idempotency_key(value: str) -> str:
        if not isinstance(value, str):
            raise ReviewJobCreationError("idempotency key must be a string")
        key = value.strip()
        if not key or len(key) > MAX_IDEMPOTENCY_KEY_LENGTH:
            raise ReviewJobCreationError("idempotency key must contain 1 to 255 characters")
        if any(ord(character) < 32 or ord(character) == 127 for character in key):
            raise ReviewJobCreationError("idempotency key must not contain control characters")
        return key

    @staticmethod
    def _ensure_same_request(
        job: ReviewJobModel,
        *,
        document_id: UUID,
        review_pack_reference_id: UUID,
        requested_by_user_id: UUID | None,
        retry_of_job_id: UUID | None,
    ) -> None:
        request_identity = (
            job.document_id,
            job.review_pack_reference_id,
            job.requested_by_user_id,
            job.retry_of_job_id,
        )
        if request_identity != (
            document_id,
            review_pack_reference_id,
            requested_by_user_id,
            retry_of_job_id,
        ):
            raise IdempotencyConflictError(
                "idempotency key is already associated with another review request"
            )
