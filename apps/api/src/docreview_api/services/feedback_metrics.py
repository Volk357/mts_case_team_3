"""Operational product metrics derived from findings and analyst feedback."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Select, and_, select
from sqlalchemy.orm import Session

from docreview_api.db.models import (
    FindingFeedbackModel,
    FindingModel,
    ReviewJobModel,
    ReviewPackReferenceModel,
)
from docreview_api.models.finding_feedback import FeedbackDecision

QUALITY_SCOPE = (
    "Operational feedback metrics only. Recall@20 must be measured separately "
    "against a labeled evaluation set."
)


class InvalidFeedbackMetricsFilter(ValueError):
    """The requested metrics range is ambiguous or invalid."""


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _share(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


@dataclass(frozen=True, slots=True)
class DefectFalsePositiveSnapshot:
    defect_id: str
    evaluated_decisions: int
    false_positive_decisions: int
    false_positive_rate: float | None


@dataclass(frozen=True, slots=True)
class FeedbackMetricsSnapshot:
    total_findings: int
    evaluated_findings: int
    unevaluated_findings: int
    unevaluated_share: float | None
    total_decisions: int
    accepted_decisions: int
    accepted_share: float | None
    false_positive_by_defect: tuple[DefectFalsePositiveSnapshot, ...]
    average_time_to_first_decision_seconds: float | None
    quality_scope: str = QUALITY_SCOPE


class FeedbackMetricsService:
    """Calculate tenant-wide feedback funnel metrics without altering review results."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def calculate(
        self,
        *,
        company_id: UUID,
        finding_created_from: datetime | None = None,
        finding_created_to: datetime | None = None,
        review_pack_id: UUID | None = None,
    ) -> FeedbackMetricsSnapshot:
        start, end = self.validate_filters(
            finding_created_from=finding_created_from,
            finding_created_to=finding_created_to,
        )
        statement = self._statement(company_id=company_id)
        if start is not None:
            statement = statement.where(FindingModel.created_at >= start)
        if end is not None:
            statement = statement.where(FindingModel.created_at <= end)
        if review_pack_id is not None:
            statement = statement.where(ReviewPackReferenceModel.id == review_pack_id)

        finding_ids: set[UUID] = set()
        evaluated_finding_ids: set[UUID] = set()
        first_decision_at: dict[UUID, datetime] = {}
        finding_created_at: dict[UUID, datetime] = {}
        decisions_by_defect: dict[str, list[int]] = {}
        total_decisions = 0
        accepted_decisions = 0

        for finding_id, defect_id, created_at, decision, decided_at in self._session.execute(
            statement
        ):
            finding_ids.add(finding_id)
            finding_created_at[finding_id] = _as_utc(created_at)
            counters = decisions_by_defect.setdefault(defect_id, [0, 0])
            if decision is None or decided_at is None:
                continue
            evaluated_finding_ids.add(finding_id)
            total_decisions += 1
            counters[0] += 1
            if decision == FeedbackDecision.ACCEPTED.value:
                accepted_decisions += 1
            if decision == FeedbackDecision.FALSE_POSITIVE.value:
                counters[1] += 1
            decided_at_utc = _as_utc(decided_at)
            previous = first_decision_at.get(finding_id)
            if previous is None or decided_at_utc < previous:
                first_decision_at[finding_id] = decided_at_utc

        unevaluated_findings = len(finding_ids - evaluated_finding_ids)
        durations = [
            (decided_at - finding_created_at[finding_id]).total_seconds()
            for finding_id, decided_at in first_decision_at.items()
            if decided_at >= finding_created_at[finding_id]
        ]
        by_defect = tuple(
            DefectFalsePositiveSnapshot(
                defect_id=defect_id,
                evaluated_decisions=counters[0],
                false_positive_decisions=counters[1],
                false_positive_rate=_share(counters[1], counters[0]),
            )
            for defect_id, counters in sorted(decisions_by_defect.items())
        )
        return FeedbackMetricsSnapshot(
            total_findings=len(finding_ids),
            evaluated_findings=len(evaluated_finding_ids),
            unevaluated_findings=unevaluated_findings,
            unevaluated_share=_share(unevaluated_findings, len(finding_ids)),
            total_decisions=total_decisions,
            accepted_decisions=accepted_decisions,
            accepted_share=_share(accepted_decisions, total_decisions),
            false_positive_by_defect=by_defect,
            average_time_to_first_decision_seconds=(
                round(sum(durations) / len(durations), 3) if durations else None
            ),
        )

    @classmethod
    def validate_filters(
        cls,
        *,
        finding_created_from: datetime | None,
        finding_created_to: datetime | None,
    ) -> tuple[datetime | None, datetime | None]:
        start = cls._validate_boundary(finding_created_from)
        end = cls._validate_boundary(finding_created_to)
        if start is not None and end is not None and start > end:
            raise InvalidFeedbackMetricsFilter(
                "finding_created_from must not follow finding_created_to"
            )
        return start, end

    @staticmethod
    def _validate_boundary(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise InvalidFeedbackMetricsFilter("metrics timestamps must include a timezone")
        return value.astimezone(UTC)

    @staticmethod
    def _statement(*, company_id: UUID) -> Select[tuple[UUID, str, datetime, str, datetime]]:
        return (
            select(
                FindingModel.id,
                FindingModel.defect_id,
                FindingModel.created_at,
                FindingFeedbackModel.decision,
                FindingFeedbackModel.created_at,
            )
            .select_from(FindingModel)
            .join(ReviewJobModel, ReviewJobModel.id == FindingModel.review_job_id)
            .join(
                ReviewPackReferenceModel,
                ReviewPackReferenceModel.id == ReviewJobModel.review_pack_reference_id,
            )
            .outerjoin(
                FindingFeedbackModel,
                and_(
                    FindingFeedbackModel.finding_id == FindingModel.id,
                    FindingFeedbackModel.company_id == company_id,
                ),
            )
            .where(
                FindingModel.company_id == company_id,
                ReviewJobModel.company_id == company_id,
                ReviewPackReferenceModel.company_id == company_id,
            )
            .order_by(FindingModel.id, FindingFeedbackModel.created_at)
        )
