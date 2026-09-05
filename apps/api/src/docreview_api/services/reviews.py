"""Tenant-safe read model for the public Reviews API."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from docreview_api.db.models import DocumentModel, FindingModel, ReviewJobModel
from docreview_api.models.review_job_state import ReviewJobStatus


class ReviewUnavailableError(LookupError):
    """The review does not exist in the requesting tenant."""


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class ReviewSnapshot:
    id: UUID
    document_id: UUID
    review_pack_id: UUID
    status: ReviewJobStatus
    queued_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error_code: str | None
    user_error_message: str | None
    error_retriable: bool | None


DetectionLayer = Literal["rule", "model", "mixed"]

# `detected_by` contains private analyzer names. Fold known markers into a
# closed public vocabulary; any unknown marker makes the layer indeterminate.
_RULE_MARKERS = frozenset({"deterministic"})
_MODEL_MARKERS = frozenset({"model"})


def _detection_layer(detected_by: list[str]) -> DetectionLayer | None:
    names = {str(name).strip().lower() for name in detected_by}
    if not names or not names <= (_RULE_MARKERS | _MODEL_MARKERS):
        # Хотя бы одно незнакомое имя — значит происхождение известно неполно.
        # Сказать «найдено моделью», когда вклад внесла ещё и неизвестная
        # проверка, значит подсунуть аналитику неверную оценку надёжности.
        return None
    rule = bool(names & _RULE_MARKERS)
    model = bool(names & _MODEL_MARKERS)
    if rule and model:
        return "mixed"
    return "rule" if rule else "model"


@dataclass(frozen=True, slots=True)
class ReviewListItem:
    """One compact row in review history."""

    id: UUID
    document_id: UUID
    document_filename: str
    status: ReviewJobStatus
    queued_at: datetime
    finished_at: datetime | None
    findings_count: int


@dataclass(frozen=True, slots=True)
class FindingSnapshot:
    id: UUID
    ordinal: int
    defect_id: str
    severity: str
    confidence: float
    location: dict[str, Any]
    quote: str
    problem: str
    clarification: str
    detection_layer: DetectionLayer | None


@dataclass(frozen=True, slots=True)
class ReviewWarningSnapshot:
    code: str | None
    message: str


@dataclass(frozen=True, slots=True)
class ReviewFindingsSnapshot:
    items: tuple[FindingSnapshot, ...]
    warnings: tuple[ReviewWarningSnapshot, ...]


def _public_warnings(raw_result: dict[str, Any] | None) -> tuple[ReviewWarningSnapshot, ...]:
    if not isinstance(raw_result, dict):
        return ()
    source = raw_result.get("warnings")
    if not isinstance(source, list):
        return ()

    warnings: list[ReviewWarningSnapshot] = []
    for warning in source:
        if isinstance(warning, str) and warning:
            warnings.append(ReviewWarningSnapshot(code=None, message=warning))
        elif isinstance(warning, dict):
            code = warning.get("code")
            message = warning.get("message")
            if isinstance(message, str) and message:
                warnings.append(
                    ReviewWarningSnapshot(
                        code=code if isinstance(code, str) and code else None,
                        message=message,
                    )
                )
    return tuple(warnings)


class ReviewQueryService:
    """Read review state without leaking worker or model configuration."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get(self, review_id: UUID, *, company_id: UUID) -> ReviewSnapshot:
        with self._session_factory() as session:
            job = session.scalar(
                select(ReviewJobModel).where(
                    ReviewJobModel.id == review_id,
                    ReviewJobModel.company_id == company_id,
                )
            )
            if job is None:
                raise ReviewUnavailableError
            return self._snapshot(job)

    def list_recent(self, *, company_id: UUID, limit: int = 50) -> tuple[ReviewListItem, ...]:
        """Return recent tenant reviews with a correlated finding count."""
        findings_count = (
            select(func.count(FindingModel.id))
            .where(FindingModel.review_job_id == ReviewJobModel.id)
            .correlate(ReviewJobModel)
            .scalar_subquery()
        )
        with self._session_factory() as session:
            rows = session.execute(
                select(ReviewJobModel, DocumentModel.original_filename, findings_count)
                .join(DocumentModel, DocumentModel.id == ReviewJobModel.document_id)
                .where(ReviewJobModel.company_id == company_id)
                .order_by(ReviewJobModel.queued_at.desc())
                .limit(limit)
            ).all()
            return tuple(
                ReviewListItem(
                    id=job.id,
                    document_id=job.document_id,
                    document_filename=filename,
                    status=job.status,
                    queued_at=self._queued_at(job),
                    finished_at=_utc(
                        job.completed_at or job.failed_at or job.timed_out_at or job.cancelled_at
                    ),
                    findings_count=count,
                )
                for job, filename, count in rows
            )

    def get_findings(self, review_id: UUID, *, company_id: UUID) -> ReviewFindingsSnapshot:
        with self._session_factory() as session:
            job = session.scalar(
                select(ReviewJobModel).where(
                    ReviewJobModel.id == review_id,
                    ReviewJobModel.company_id == company_id,
                )
            )
            if job is None:
                raise ReviewUnavailableError
            findings = session.scalars(
                select(FindingModel)
                .where(
                    FindingModel.review_job_id == review_id,
                    FindingModel.company_id == company_id,
                )
                .order_by(FindingModel.ordinal)
            ).all()
            return ReviewFindingsSnapshot(
                items=tuple(
                    FindingSnapshot(
                        id=item.id,
                        ordinal=item.ordinal,
                        defect_id=item.defect_id,
                        severity=item.severity,
                        confidence=item.confidence,
                        location=item.location,
                        quote=item.quote,
                        problem=item.problem,
                        clarification=item.clarification,
                        detection_layer=_detection_layer(item.detected_by),
                    )
                    for item in findings
                ),
                warnings=_public_warnings(job.raw_result),
            )

    @staticmethod
    def _queued_at(job: ReviewJobModel) -> datetime:
        queued_at = _utc(job.queued_at)
        assert queued_at is not None
        return queued_at

    @staticmethod
    def _snapshot(job: ReviewJobModel) -> ReviewSnapshot:
        finished = job.completed_at or job.failed_at or job.timed_out_at or job.cancelled_at
        queued_at = _utc(job.queued_at)
        assert queued_at is not None
        return ReviewSnapshot(
            id=job.id,
            document_id=job.document_id,
            review_pack_id=job.review_pack_reference_id,
            status=job.status,
            queued_at=queued_at,
            started_at=_utc(job.started_at),
            finished_at=_utc(finished),
            error_code=job.error_code,
            user_error_message=job.user_error_message,
            error_retriable=job.error_retriable,
        )
