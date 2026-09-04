"""SQLAlchemy mappings for Product Application persistence."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from docreview_api.db.base import Base
from docreview_api.models.review_job_state import ReviewJobStatus


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp for application-created rows."""

    return datetime.now(UTC)


class TimestampMixin:
    """Common audit timestamps."""

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class CompanyModel(TimestampMixin, Base):
    __tablename__ = "companies"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    display_name: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    users: Mapped[list[UserModel]] = relationship(back_populates="company")
    documents: Mapped[list[DocumentModel]] = relationship(back_populates="company")
    review_packs: Mapped[list[ReviewPackReferenceModel]] = relationship(back_populates="company")
    review_jobs: Mapped[list[ReviewJobModel]] = relationship(back_populates="company")


class UserModel(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("company_id", "external_subject", name="uq_users_company_subject"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="RESTRICT"), index=True
    )
    external_subject: Mapped[str | None] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(320))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    company: Mapped[CompanyModel] = relationship(back_populates="users")


class DocumentModel(TimestampMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint("size_bytes >= 0", name="size_non_negative"),
        CheckConstraint("length(sha256) = 64", name="sha256_length"),
        UniqueConstraint("storage_key", name="uq_documents_storage_key"),
        Index("ix_documents_company_sha256", "company_id", "sha256"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(ForeignKey("companies.id", ondelete="RESTRICT"))
    uploaded_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    original_filename: Mapped[str] = mapped_column(String(500))
    media_type: Mapped[str] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(1000))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    company: Mapped[CompanyModel] = relationship(back_populates="documents")
    uploaded_by: Mapped[UserModel | None] = relationship()
    review_jobs: Mapped[list[ReviewJobModel]] = relationship(back_populates="document")


class ReviewPackReferenceModel(TimestampMixin, Base):
    __tablename__ = "review_pack_references"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "pack_key", "version", name="uq_review_packs_company_key_version"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="RESTRICT"), index=True
    )
    pack_key: Mapped[str] = mapped_column(String(255))
    version: Mapped[str] = mapped_column(String(100))
    display_name: Mapped[str] = mapped_column(String(255))
    document_type: Mapped[str] = mapped_column(
        String(100), default="technical_specification", server_default="technical_specification"
    )
    locator: Mapped[str] = mapped_column(String(1000))
    checksum: Mapped[str | None] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    company: Mapped[CompanyModel] = relationship(back_populates="review_packs")
    review_jobs: Mapped[list[ReviewJobModel]] = relationship(back_populates="review_pack")


class ReviewJobModel(TimestampMixin, Base):
    __tablename__ = "review_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'timed_out', 'cancelled')",
            name="status_valid",
        ),
        CheckConstraint("process_pid IS NULL OR process_pid > 0", name="process_pid_positive"),
        Index("ix_review_jobs_status", "status"),
        Index("ix_review_jobs_document_id", "document_id"),
        Index("ix_review_jobs_created_at", "created_at"),
        UniqueConstraint(
            "company_id", "idempotency_key", name="uq_review_jobs_company_idempotency"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    run_id: Mapped[str] = mapped_column(String(128), unique=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255))
    company_id: Mapped[UUID] = mapped_column(ForeignKey("companies.id", ondelete="RESTRICT"))
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"))
    review_pack_reference_id: Mapped[UUID] = mapped_column(
        ForeignKey("review_pack_references.id", ondelete="RESTRICT")
    )
    requested_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    retry_of_job_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("review_jobs.id", ondelete="SET NULL")
    )
    status: Mapped[ReviewJobStatus] = mapped_column(
        Enum(
            ReviewJobStatus,
            name="review_job_status",
            native_enum=False,
            create_constraint=False,
            values_callable=lambda enum: [item.value for item in enum],
        ),
        default=ReviewJobStatus.QUEUED,
    )
    raw_result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    schema_version: Mapped[str | None] = mapped_column(String(50))
    engine_version: Mapped[str | None] = mapped_column(String(100))
    result_review_pack_id: Mapped[str | None] = mapped_column(String(255))
    result_review_pack_version: Mapped[str | None] = mapped_column(String(100))
    model_name: Mapped[str | None] = mapped_column(String(255))
    prompt_versions: Mapped[dict[str, str] | None] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(100))
    user_error_message: Mapped[str | None] = mapped_column(Text)
    diagnostic_message: Mapped[str | None] = mapped_column(Text)
    error_retriable: Mapped[bool | None] = mapped_column(Boolean)
    process_pid: Mapped[int | None] = mapped_column(Integer)
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    timed_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    company: Mapped[CompanyModel] = relationship(back_populates="review_jobs")
    document: Mapped[DocumentModel] = relationship(back_populates="review_jobs")
    review_pack: Mapped[ReviewPackReferenceModel] = relationship(back_populates="review_jobs")
    requested_by: Mapped[UserModel | None] = relationship(foreign_keys=[requested_by_user_id])
    retry_of: Mapped[ReviewJobModel | None] = relationship(remote_side=[id])
    findings: Mapped[list[FindingModel]] = relationship(
        back_populates="review_job", cascade="all, delete-orphan", passive_deletes=True
    )


class FindingModel(Base):
    __tablename__ = "findings"
    __table_args__ = (
        UniqueConstraint("review_job_id", "core_finding_id", name="uq_findings_job_core_id"),
        UniqueConstraint("review_job_id", "ordinal", name="uq_findings_job_ordinal"),
        CheckConstraint("ordinal >= 0 AND ordinal < 20", name="ordinal_range"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="RESTRICT"), index=True
    )
    review_job_id: Mapped[UUID] = mapped_column(
        ForeignKey("review_jobs.id", ondelete="CASCADE"), index=True
    )
    core_finding_id: Mapped[str] = mapped_column(String(255))
    ordinal: Mapped[int] = mapped_column(Integer)
    defect_id: Mapped[str] = mapped_column(String(255), index=True)
    severity: Mapped[str] = mapped_column(String(20), index=True)
    confidence: Mapped[float] = mapped_column(Float)
    location: Mapped[dict[str, Any]] = mapped_column(JSON)
    quote: Mapped[str] = mapped_column(Text)
    problem: Mapped[str] = mapped_column(Text)
    clarification: Mapped[str] = mapped_column(Text)
    detected_by: Mapped[list[str]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    review_job: Mapped[ReviewJobModel] = relationship(back_populates="findings")
    feedback: Mapped[list[FindingFeedbackModel]] = relationship(
        back_populates="finding", cascade="all, delete-orphan", passive_deletes=True
    )


class FindingFeedbackModel(TimestampMixin, Base):
    __tablename__ = "finding_feedback"
    __table_args__ = (
        CheckConstraint(
            "decision IN ('accepted', 'false_positive', 'allowed_exception', "
            "'already_described', 'not_relevant')",
            name="decision_valid",
        ),
        CheckConstraint(
            "length(actor_key) >= 1 AND length(actor_key) <= 255",
            name="actor_key_length",
        ),
        CheckConstraint(
            "comment IS NULL OR length(comment) <= 4000",
            name="comment_length",
        ),
        UniqueConstraint("finding_id", "actor_key", name="uq_feedback_finding_actor"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="RESTRICT"), index=True
    )
    finding_id: Mapped[UUID] = mapped_column(
        ForeignKey("findings.id", ondelete="CASCADE"), index=True
    )
    submitted_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    actor_key: Mapped[str] = mapped_column(String(255))
    decision: Mapped[str] = mapped_column(String(50))
    comment: Mapped[str | None] = mapped_column(Text)

    finding: Mapped[FindingModel] = relationship(back_populates="feedback")
    submitted_by: Mapped[UserModel | None] = relationship()
