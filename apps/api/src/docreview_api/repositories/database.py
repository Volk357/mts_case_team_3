"""Synchronous SQLAlchemy repositories and atomic review completion."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Generic, TypeVar, cast
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session, sessionmaker

from docreview_api.db.base import Base
from docreview_api.db.models import (
    CompanyModel,
    DocumentModel,
    FindingFeedbackModel,
    FindingModel,
    ReviewJobModel,
    ReviewPackReferenceModel,
    UserModel,
    utc_now,
)
from docreview_api.models.review_job_state import (
    FAILED_STATUSES,
    ReviewJobFailure,
    ReviewJobLifecycle,
    ReviewJobStatus,
)
from docreview_api.models.review_result import ReviewResultSnapshot

ModelT = TypeVar("ModelT", bound=Base)


class EntityNotFoundError(LookupError):
    """Raised when a required persisted entity does not exist."""


class TenantBoundaryError(ValueError):
    """Raised when related entities belong to different companies."""


class ReviewResultConflictError(ValueError):
    """Raised when a job already owns a different immutable result."""


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


class Repository(Generic[ModelT]):
    """Small explicit repository base; transaction ownership stays with the caller."""

    model: type[ModelT]

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, entity: ModelT) -> ModelT:
        self.session.add(entity)
        self.session.flush()
        return entity

    def get(self, entity_id: UUID) -> ModelT | None:
        return self.session.get(self.model, entity_id)

    def require(self, entity_id: UUID) -> ModelT:
        entity = self.get(entity_id)
        if entity is None:
            raise EntityNotFoundError(f"{self.model.__name__} {entity_id} was not found")
        return entity


class CompanyRepository(Repository[CompanyModel]):
    model = CompanyModel


class UserRepository(Repository[UserModel]):
    model = UserModel


class DocumentRepository(Repository[DocumentModel]):
    model = DocumentModel

    def add(self, entity: DocumentModel) -> DocumentModel:
        if entity.uploaded_by_user_id is not None:
            user = self.session.get(UserModel, entity.uploaded_by_user_id)
            if user is None:
                raise EntityNotFoundError("document user was not found")
            if user.company_id != entity.company_id:
                raise TenantBoundaryError("document and user must belong to the same company")
        return super().add(entity)


class ReviewPackReferenceRepository(Repository[ReviewPackReferenceModel]):
    model = ReviewPackReferenceModel


class FindingRepository(Repository[FindingModel]):
    model = FindingModel

    def add(self, entity: FindingModel) -> FindingModel:
        job = self.session.get(ReviewJobModel, entity.review_job_id)
        if job is None:
            raise EntityNotFoundError("finding review job was not found")
        if job.company_id != entity.company_id:
            raise TenantBoundaryError("finding and review job must belong to the same company")
        return super().add(entity)

    def list_for_job(self, review_job_id: UUID) -> list[FindingModel]:
        statement = (
            select(FindingModel)
            .where(FindingModel.review_job_id == review_job_id)
            .order_by(FindingModel.ordinal)
        )
        return list(self.session.scalars(statement))


class FindingFeedbackRepository(Repository[FindingFeedbackModel]):
    model = FindingFeedbackModel

    def add(self, entity: FindingFeedbackModel) -> FindingFeedbackModel:
        finding = self.session.get(FindingModel, entity.finding_id)
        if finding is None:
            raise EntityNotFoundError("feedback finding was not found")
        if finding.company_id != entity.company_id:
            raise TenantBoundaryError("feedback and finding must belong to the same company")
        if entity.submitted_by_user_id is not None:
            user = self.session.get(UserModel, entity.submitted_by_user_id)
            if user is None:
                raise EntityNotFoundError("feedback user was not found")
            if user.company_id != entity.company_id:
                raise TenantBoundaryError("feedback and user must belong to the same company")
        return super().add(entity)

    def upsert(
        self,
        *,
        company_id: UUID,
        finding_id: UUID,
        actor_key: str,
        decision: str,
        comment: str | None,
        submitted_by_user_id: UUID | None = None,
    ) -> FindingFeedbackModel:
        """Atomically create or replace an actor's current decision."""

        finding = self.session.get(FindingModel, finding_id)
        if finding is None:
            raise EntityNotFoundError(f"FindingModel {finding_id} was not found")
        if finding.company_id != company_id:
            raise TenantBoundaryError("feedback and finding must belong to the same company")
        if submitted_by_user_id is not None:
            user = self.session.get(UserModel, submitted_by_user_id)
            if user is None:
                raise EntityNotFoundError(f"UserModel {submitted_by_user_id} was not found")
            if user.company_id != company_id:
                raise TenantBoundaryError("feedback and user must belong to the same company")

        now = utc_now()
        values = {
            "id": uuid4(),
            "company_id": company_id,
            "finding_id": finding_id,
            "submitted_by_user_id": submitted_by_user_id,
            "actor_key": actor_key,
            "decision": decision,
            "comment": comment,
            "created_at": now,
            "updated_at": now,
        }
        updates = {
            "submitted_by_user_id": submitted_by_user_id,
            "decision": decision,
            "comment": comment,
            "updated_at": now,
        }
        dialect_name = self.session.get_bind().dialect.name
        if dialect_name == "sqlite":
            sqlite_statement = sqlite_insert(FindingFeedbackModel).values(**values)
            sqlite_statement = sqlite_statement.on_conflict_do_update(
                index_elements=["finding_id", "actor_key"],
                set_=updates,
            )
            feedback_id = self.session.scalar(sqlite_statement.returning(FindingFeedbackModel.id))
        elif dialect_name == "postgresql":
            postgresql_statement = postgresql_insert(FindingFeedbackModel).values(**values)
            postgresql_statement = postgresql_statement.on_conflict_do_update(
                constraint="uq_feedback_finding_actor",
                set_=updates,
            )
            feedback_id = self.session.scalar(
                postgresql_statement.returning(FindingFeedbackModel.id)
            )
        else:
            raise RuntimeError(f"unsupported feedback upsert dialect: {dialect_name}")

        if feedback_id is None:  # pragma: no cover - RETURNING is a database invariant
            raise RuntimeError("feedback upsert did not return an identifier")
        feedback = self.session.get(FindingFeedbackModel, feedback_id, populate_existing=True)
        if feedback is None:  # pragma: no cover - row was returned by the same transaction
            raise RuntimeError("feedback upsert did not persist a row")
        return feedback


class ReviewJobRepository(Repository[ReviewJobModel]):
    model = ReviewJobModel

    def add(self, entity: ReviewJobModel) -> ReviewJobModel:
        document = self.session.get(DocumentModel, entity.document_id)
        review_pack = self.session.get(ReviewPackReferenceModel, entity.review_pack_reference_id)
        if document is None or review_pack is None:
            raise EntityNotFoundError("review job document or Review Pack was not found")
        related_company_ids = {document.company_id, review_pack.company_id}
        if entity.requested_by_user_id is not None:
            user = self.session.get(UserModel, entity.requested_by_user_id)
            if user is None:
                raise EntityNotFoundError("review job user was not found")
            related_company_ids.add(user.company_id)
        if entity.retry_of_job_id is not None:
            previous_job = self.session.get(ReviewJobModel, entity.retry_of_job_id)
            if previous_job is None:
                raise EntityNotFoundError("previous review job was not found")
            related_company_ids.add(previous_job.company_id)
        if related_company_ids != {entity.company_id}:
            raise TenantBoundaryError("review job relations must belong to the same company")
        return super().add(entity)

    def _locked(self, job_id: UUID) -> ReviewJobModel:
        statement = select(ReviewJobModel).where(ReviewJobModel.id == job_id).with_for_update()
        job = self.session.scalar(statement)
        if job is None:
            raise EntityNotFoundError(f"ReviewJobModel {job_id} was not found")
        return job

    @staticmethod
    def _lifecycle(job: ReviewJobModel) -> ReviewJobLifecycle:
        queued_at = _as_utc(job.queued_at)
        updated_at = _as_utc(job.updated_at)
        if queued_at is None or updated_at is None:  # pragma: no cover - database invariant
            raise ValueError("review job timestamps are missing")
        failure = None
        if job.status in FAILED_STATUSES:
            if job.error_code is None or job.user_error_message is None:
                raise ValueError("failed review job details are missing")
            failure = ReviewJobFailure(
                error_code=job.error_code,
                user_message=job.user_error_message,
                diagnostic_message=job.diagnostic_message,
                retriable=bool(job.error_retriable),
            )
        return ReviewJobLifecycle(
            status=job.status,
            queued_at=queued_at,
            updated_at=updated_at,
            started_at=_as_utc(job.started_at),
            completed_at=_as_utc(job.completed_at),
            failed_at=_as_utc(job.failed_at),
            timed_out_at=_as_utc(job.timed_out_at),
            cancelled_at=_as_utc(job.cancelled_at),
            failure=failure,
        )

    @staticmethod
    def _apply_lifecycle(job: ReviewJobModel, lifecycle: ReviewJobLifecycle) -> None:
        job.status = lifecycle.status
        job.queued_at = lifecycle.queued_at
        job.started_at = lifecycle.started_at
        job.completed_at = lifecycle.completed_at
        job.failed_at = lifecycle.failed_at
        job.timed_out_at = lifecycle.timed_out_at
        job.cancelled_at = lifecycle.cancelled_at
        job.updated_at = lifecycle.updated_at

    def start(
        self, job_id: UUID, *, at: datetime, process_pid: int | None = None
    ) -> ReviewJobModel:
        if process_pid is not None and process_pid <= 0:
            raise ValueError("process_pid must be positive")
        job = self._locked(job_id)
        lifecycle = self._lifecycle(job).transition_to(ReviewJobStatus.RUNNING, at=at)
        self._apply_lifecycle(job, lifecycle)
        job.process_pid = process_pid
        self.session.flush()
        return job

    def claim_next(self, *, at: datetime) -> ReviewJobModel | None:
        """Atomically claim the oldest queued job using a compare-and-set update."""

        candidate_id = (
            select(ReviewJobModel.id)
            .where(ReviewJobModel.status == ReviewJobStatus.QUEUED)
            .order_by(ReviewJobModel.queued_at, ReviewJobModel.id)
            .limit(1)
            .scalar_subquery()
        )
        statement = (
            update(ReviewJobModel)
            .where(
                ReviewJobModel.id == candidate_id,
                ReviewJobModel.status == ReviewJobStatus.QUEUED,
            )
            .values(
                status=ReviewJobStatus.RUNNING,
                started_at=at,
                updated_at=at,
                process_pid=None,
            )
            .returning(ReviewJobModel.id)
            .execution_options(synchronize_session=False)
        )
        job_id = self.session.scalar(statement)
        if job_id is None:
            return None
        job = self.session.get(ReviewJobModel, job_id)
        if job is None:  # pragma: no cover - returned row must still exist in this transaction
            raise EntityNotFoundError(f"ReviewJobModel {job_id} was not found after claim")
        return job

    def attach_process(self, job_id: UUID, *, process_pid: int) -> bool:
        """Attach a child PID only while this claim remains running."""

        if process_pid <= 0:
            raise ValueError("process_pid must be positive")
        statement = (
            update(ReviewJobModel)
            .where(
                ReviewJobModel.id == job_id,
                ReviewJobModel.status == ReviewJobStatus.RUNNING,
                ReviewJobModel.process_pid.is_(None),
            )
            .values(process_pid=process_pid)
            .execution_options(synchronize_session=False)
        )
        result = cast(CursorResult[Any], self.session.execute(statement))
        return result.rowcount == 1

    def fail_running(
        self,
        job_id: UUID,
        *,
        at: datetime,
        failure: ReviewJobFailure,
    ) -> bool:
        """Fail a claimed job without overwriting a concurrent terminal decision."""

        statement = (
            update(ReviewJobModel)
            .where(
                ReviewJobModel.id == job_id,
                ReviewJobModel.status == ReviewJobStatus.RUNNING,
            )
            .values(
                status=ReviewJobStatus.FAILED,
                failed_at=at,
                updated_at=at,
                process_pid=None,
                error_code=failure.error_code,
                user_error_message=failure.user_message,
                diagnostic_message=failure.diagnostic_message,
                error_retriable=failure.retriable,
            )
            .execution_options(synchronize_session=False)
        )
        result = cast(CursorResult[Any], self.session.execute(statement))
        return result.rowcount == 1

    def fail_stale_running(
        self,
        *,
        updated_before: datetime,
        at: datetime,
        failure: ReviewJobFailure,
    ) -> tuple[UUID, ...]:
        """Atomically terminalize leases abandoned by a previous worker process."""

        statement = (
            update(ReviewJobModel)
            .where(
                ReviewJobModel.status == ReviewJobStatus.RUNNING,
                ReviewJobModel.updated_at <= updated_before,
            )
            .values(
                status=ReviewJobStatus.FAILED,
                failed_at=at,
                updated_at=at,
                process_pid=None,
                error_code=failure.error_code,
                user_error_message=failure.user_message,
                diagnostic_message=failure.diagnostic_message,
                error_retriable=failure.retriable,
            )
            .returning(ReviewJobModel.id)
            .execution_options(synchronize_session=False)
        )
        return tuple(self.session.scalars(statement))

    def timed_out(self, job_id: UUID, *, at: datetime, failure: ReviewJobFailure) -> ReviewJobModel:
        return self._finish_without_result(
            job_id,
            target=ReviewJobStatus.TIMED_OUT,
            at=at,
            failure=failure,
        )

    def fail(self, job_id: UUID, *, at: datetime, failure: ReviewJobFailure) -> ReviewJobModel:
        return self._finish_without_result(
            job_id,
            target=ReviewJobStatus.FAILED,
            at=at,
            failure=failure,
        )

    def cancel(self, job_id: UUID, *, at: datetime, failure: ReviewJobFailure) -> ReviewJobModel:
        return self._finish_without_result(
            job_id,
            target=ReviewJobStatus.CANCELLED,
            at=at,
            failure=failure,
        )

    def _finish_without_result(
        self,
        job_id: UUID,
        *,
        target: ReviewJobStatus,
        at: datetime,
        failure: ReviewJobFailure,
    ) -> ReviewJobModel:
        job = self._locked(job_id)
        if job.status is target:
            return job
        lifecycle = self._lifecycle(job).transition_to(target, at=at, failure=failure)
        self._apply_lifecycle(job, lifecycle)
        job.error_code = failure.error_code
        job.user_error_message = failure.user_message
        job.diagnostic_message = failure.diagnostic_message
        job.error_retriable = failure.retriable
        self.session.flush()
        return job

    def complete(
        self,
        job_id: UUID,
        snapshot: ReviewResultSnapshot,
        *,
        at: datetime,
    ) -> ReviewJobModel:
        if snapshot.status != "completed":
            raise ReviewResultConflictError("only a completed ReviewResult can complete a job")
        job = self._locked(job_id)
        if job.status is ReviewJobStatus.COMPLETED:
            if job.raw_result == snapshot.raw_result:
                return job
            raise ReviewResultConflictError("review job already has a different result")
        if job.run_id != snapshot.run_id:
            raise ReviewResultConflictError("ReviewResult run_id does not match review job")
        if job.document.sha256.casefold() != snapshot.document_sha256.casefold():
            raise ReviewResultConflictError("ReviewResult SHA-256 does not match document")
        if (
            job.review_pack.pack_key != snapshot.versions.review_pack_id
            or job.review_pack.version != snapshot.versions.review_pack_version
        ):
            raise ReviewResultConflictError("ReviewResult Review Pack does not match review job")

        lifecycle = self._lifecycle(job).transition_to(ReviewJobStatus.COMPLETED, at=at)
        self._apply_lifecycle(job, lifecycle)
        job.raw_result = snapshot.raw_result
        job.schema_version = snapshot.versions.schema_version
        job.engine_version = snapshot.versions.core_version
        job.result_review_pack_id = snapshot.versions.review_pack_id
        job.result_review_pack_version = snapshot.versions.review_pack_version
        job.model_name = snapshot.versions.model_name
        job.prompt_versions = snapshot.versions.prompt_versions
        for projected in snapshot.findings:
            job.findings.append(
                FindingModel(
                    company_id=job.company_id,
                    core_finding_id=projected.core_finding_id,
                    ordinal=projected.ordinal,
                    defect_id=projected.defect_id,
                    severity=projected.severity,
                    confidence=projected.confidence,
                    location=projected.location,
                    quote=projected.quote,
                    problem=projected.problem,
                    clarification=projected.clarification,
                    detected_by=list(projected.detected_by),
                )
            )
        self.session.flush()
        return job


def complete_review_job(
    session_factory: sessionmaker[Session],
    job_id: UUID,
    snapshot: ReviewResultSnapshot,
    *,
    at: datetime,
) -> ReviewJobModel:
    """Atomically persist the immutable raw result and every finding projection."""

    with session_factory.begin() as session:
        return ReviewJobRepository(session).complete(job_id, snapshot, at=at)
