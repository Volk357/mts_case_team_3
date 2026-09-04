"""Finding feedback endpoint."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session, sessionmaker

from docreview_api.api.schemas.common import OpaqueId
from docreview_api.api.schemas.errors import ApiError
from docreview_api.api.schemas.feedback import (
    FeedbackListResponse,
    FeedbackResponse,
    FeedbackUpsertRequest,
)
from docreview_api.config import Settings, get_settings
from docreview_api.db.dependencies import get_session_factory
from docreview_api.services.finding_feedback import (
    FindingFeedbackService,
    FindingUnavailableError,
    InvalidFeedbackError,
    ReviewUnavailableError,
)

router = APIRouter(tags=["feedback"])


@router.put("/findings/{finding_id}/feedback", response_model=FeedbackResponse)
def put_finding_feedback(
    finding_id: OpaqueId,
    request: FeedbackUpsertRequest,
    actor_key: Annotated[
        str,
        Header(alias="X-Actor-Key", min_length=1, max_length=255),
    ],
    settings: Annotated[Settings, Depends(get_settings)],
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
) -> FeedbackResponse:
    """Create or replace the current actor's decision for one finding."""

    try:
        with session_factory.begin() as session:
            snapshot = FindingFeedbackService(session).upsert(
                company_id=settings.default_company_id,
                finding_id=finding_id,
                actor_key=actor_key,
                decision=request.decision,
                comment=request.comment,
            )
    except FindingUnavailableError as error:
        raise ApiError(404, "FINDING_NOT_FOUND", "Finding was not found.") from error
    except InvalidFeedbackError as error:
        raise ApiError(422, "FEEDBACK_INVALID", "Feedback is invalid.") from error

    return FeedbackResponse(
        feedback_id=snapshot.id,
        finding_id=snapshot.finding_id,
        decision=snapshot.decision,
        comment=snapshot.comment,
        created_at=snapshot.created_at,
        updated_at=snapshot.updated_at,
    )


@router.get("/reviews/{review_id}/feedback", response_model=FeedbackListResponse)
def list_review_feedback(
    review_id: OpaqueId,
    actor_key: Annotated[
        str,
        Header(alias="X-Actor-Key", min_length=1, max_length=255),
    ],
    settings: Annotated[Settings, Depends(get_settings)],
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
) -> FeedbackListResponse:
    """Return this actor's saved decisions for one review."""

    try:
        with session_factory() as session:
            snapshots = FindingFeedbackService(session).list_for_review(
                company_id=settings.default_company_id,
                review_id=review_id,
                actor_key=actor_key,
            )
    except ReviewUnavailableError as error:
        raise ApiError(404, "REVIEW_NOT_FOUND", "Review was not found.") from error
    except InvalidFeedbackError as error:
        raise ApiError(422, "FEEDBACK_INVALID", "Feedback is invalid.") from error

    items = [
        FeedbackResponse(
            feedback_id=snapshot.id,
            finding_id=snapshot.finding_id,
            decision=snapshot.decision,
            comment=snapshot.comment,
            created_at=snapshot.created_at,
            updated_at=snapshot.updated_at,
        )
        for snapshot in snapshots
    ]
    return FeedbackListResponse(review_id=review_id, items=items, total=len(items))
