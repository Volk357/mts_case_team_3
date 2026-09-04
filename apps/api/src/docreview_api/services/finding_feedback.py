"""Validated, tenant-safe feedback upsert use case."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from docreview_api.db.models import FindingFeedbackModel, FindingModel, ReviewJobModel
from docreview_api.models.finding_feedback import FeedbackDecision
from docreview_api.repositories.database import FindingFeedbackRepository

MAX_ACTOR_KEY_LENGTH = 255
MAX_FEEDBACK_COMMENT_LENGTH = 4000


class FindingUnavailableError(LookupError):
    """The finding does not exist in the requesting tenant."""


class ReviewUnavailableError(LookupError):
    """The review does not exist in the requesting tenant."""


class InvalidFeedbackError(ValueError):
    """Feedback fields violate application-level invariants."""


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class FeedbackSnapshot:
    id: UUID
    finding_id: UUID
    decision: FeedbackDecision
    comment: str | None
    created_at: datetime
    updated_at: datetime


class FindingFeedbackService:
    """Create or update one actor's decision without mutating analysis output."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert(
        self,
        *,
        company_id: UUID,
        finding_id: UUID,
        actor_key: str,
        decision: FeedbackDecision,
        comment: str | None,
        submitted_by_user_id: UUID | None = None,
    ) -> FeedbackSnapshot:
        actor = self._validate_actor_key(actor_key)
        normalized_comment = self._validate_comment(comment)
        finding = self._session.scalar(
            select(FindingModel).where(
                FindingModel.id == finding_id,
                FindingModel.company_id == company_id,
            )
        )
        if finding is None:
            raise FindingUnavailableError

        feedback = FindingFeedbackRepository(self._session).upsert(
            company_id=company_id,
            finding_id=finding_id,
            actor_key=actor,
            decision=decision.value,
            comment=normalized_comment,
            submitted_by_user_id=submitted_by_user_id,
        )
        return self._snapshot(feedback)

    def list_for_review(
        self,
        *,
        company_id: UUID,
        review_id: UUID,
        actor_key: str,
    ) -> tuple[FeedbackSnapshot, ...]:
        actor = self._validate_actor_key(actor_key)
        review_exists = self._session.scalar(
            select(ReviewJobModel.id).where(
                ReviewJobModel.id == review_id,
                ReviewJobModel.company_id == company_id,
            )
        )
        if review_exists is None:
            raise ReviewUnavailableError

        feedback = self._session.scalars(
            select(FindingFeedbackModel)
            .join(FindingModel, FindingModel.id == FindingFeedbackModel.finding_id)
            .where(
                FindingModel.review_job_id == review_id,
                FindingFeedbackModel.company_id == company_id,
                FindingFeedbackModel.actor_key == actor,
            )
            .order_by(FindingModel.ordinal)
        ).all()
        return tuple(self._snapshot(item) for item in feedback)

    @staticmethod
    def _validate_actor_key(value: str) -> str:
        actor = value.strip()
        if not actor or len(actor) > MAX_ACTOR_KEY_LENGTH:
            raise InvalidFeedbackError("actor key must contain 1 to 255 characters")
        if any(ord(character) < 32 or ord(character) == 127 for character in actor):
            raise InvalidFeedbackError("actor key must not contain control characters")
        return actor

    @staticmethod
    def _validate_comment(value: str | None) -> str | None:
        if value is None:
            return None
        comment = value.strip()
        if len(comment) > MAX_FEEDBACK_COMMENT_LENGTH:
            raise InvalidFeedbackError("feedback comment is too long")
        return comment or None

    @staticmethod
    def _snapshot(feedback: FindingFeedbackModel) -> FeedbackSnapshot:
        return FeedbackSnapshot(
            id=feedback.id,
            finding_id=feedback.finding_id,
            decision=FeedbackDecision(feedback.decision),
            comment=feedback.comment,
            created_at=_as_utc(feedback.created_at),
            updated_at=_as_utc(feedback.updated_at),
        )
