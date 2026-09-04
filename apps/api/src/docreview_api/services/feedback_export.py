"""Tenant-safe, version-linked feedback export for quality analysis."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from docreview_api.db.models import (
    FindingFeedbackModel,
    FindingModel,
    ReviewJobModel,
    ReviewPackReferenceModel,
)
from docreview_api.models.finding_feedback import FeedbackDecision


class InvalidFeedbackExportFilter(ValueError):
    """The requested export range is ambiguous or invalid."""


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class FeedbackExportSnapshot:
    run_id: str
    review_id: UUID
    finding_id: UUID
    core_finding_id: str
    ordinal: int
    defect_id: str
    severity: str
    confidence: float
    location: dict[str, Any]
    quote: str
    problem: str
    clarification: str
    review_pack_reference_id: UUID
    review_pack_key: str
    review_pack_version: str
    result_review_pack_id: str | None
    result_review_pack_version: str | None
    schema_version: str | None
    engine_version: str | None
    model_name: str | None
    prompt_versions: dict[str, str] | None
    decision: FeedbackDecision
    comment: str | None
    feedback_created_at: datetime
    feedback_updated_at: datetime


class FeedbackExportService:
    """Read only the fields needed to evaluate finding quality."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def iter_snapshots(
        self,
        *,
        company_id: UUID,
        updated_from: datetime | None = None,
        updated_to: datetime | None = None,
        review_pack_id: UUID | None = None,
    ) -> Iterator[FeedbackExportSnapshot]:
        start, end = self.validate_filters(updated_from=updated_from, updated_to=updated_to)

        statement = self._statement(company_id=company_id)
        if start is not None:
            statement = statement.where(FindingFeedbackModel.updated_at >= start)
        if end is not None:
            statement = statement.where(FindingFeedbackModel.updated_at <= end)
        if review_pack_id is not None:
            statement = statement.where(ReviewPackReferenceModel.id == review_pack_id)

        rows = self._session.execute(statement).yield_per(500)
        for feedback, finding, review, review_pack in rows:
            yield FeedbackExportSnapshot(
                run_id=review.run_id,
                review_id=review.id,
                finding_id=finding.id,
                core_finding_id=finding.core_finding_id,
                ordinal=finding.ordinal,
                defect_id=finding.defect_id,
                severity=finding.severity,
                confidence=finding.confidence,
                location=finding.location,
                quote=finding.quote,
                problem=finding.problem,
                clarification=finding.clarification,
                review_pack_reference_id=review_pack.id,
                review_pack_key=review_pack.pack_key,
                review_pack_version=review_pack.version,
                result_review_pack_id=review.result_review_pack_id,
                result_review_pack_version=review.result_review_pack_version,
                schema_version=review.schema_version,
                engine_version=review.engine_version,
                model_name=review.model_name,
                prompt_versions=review.prompt_versions,
                decision=FeedbackDecision(feedback.decision),
                comment=feedback.comment,
                feedback_created_at=_as_utc(feedback.created_at),
                feedback_updated_at=_as_utc(feedback.updated_at),
            )

    @classmethod
    def validate_filters(
        cls,
        *,
        updated_from: datetime | None,
        updated_to: datetime | None,
    ) -> tuple[datetime | None, datetime | None]:
        start = cls._validate_boundary(updated_from)
        end = cls._validate_boundary(updated_to)
        if start is not None and end is not None and start > end:
            raise InvalidFeedbackExportFilter("updated_from must not follow updated_to")
        return start, end

    @staticmethod
    def _validate_boundary(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise InvalidFeedbackExportFilter("export timestamps must include a timezone")
        return value.astimezone(UTC)

    @staticmethod
    def _statement(
        *, company_id: UUID
    ) -> Select[
        tuple[
            FindingFeedbackModel,
            FindingModel,
            ReviewJobModel,
            ReviewPackReferenceModel,
        ]
    ]:
        return (
            select(
                FindingFeedbackModel,
                FindingModel,
                ReviewJobModel,
                ReviewPackReferenceModel,
            )
            .join(FindingModel, FindingModel.id == FindingFeedbackModel.finding_id)
            .join(ReviewJobModel, ReviewJobModel.id == FindingModel.review_job_id)
            .join(
                ReviewPackReferenceModel,
                ReviewPackReferenceModel.id == ReviewJobModel.review_pack_reference_id,
            )
            .where(
                FindingFeedbackModel.company_id == company_id,
                FindingModel.company_id == company_id,
                ReviewJobModel.company_id == company_id,
                ReviewPackReferenceModel.company_id == company_id,
            )
            .order_by(FindingFeedbackModel.updated_at, FindingFeedbackModel.id)
        )
