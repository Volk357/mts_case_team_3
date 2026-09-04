"""Finding feedback and quality export endpoints."""

from collections.abc import Iterator
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, sessionmaker

from docreview_api.api.schemas.common import OpaqueId
from docreview_api.api.schemas.errors import ApiError
from docreview_api.api.schemas.feedback import (
    FeedbackExportRecord,
    FeedbackListResponse,
    FeedbackMetricsResponse,
    FeedbackResponse,
    FeedbackUpsertRequest,
)
from docreview_api.config import Settings, get_settings
from docreview_api.db.dependencies import get_session_factory
from docreview_api.services.feedback_export import (
    FeedbackExportService,
    FeedbackExportSnapshot,
    InvalidFeedbackExportFilter,
)
from docreview_api.services.feedback_metrics import (
    FeedbackMetricsService,
    InvalidFeedbackMetricsFilter,
)
from docreview_api.services.finding_feedback import (
    FindingFeedbackService,
    FindingUnavailableError,
    InvalidFeedbackError,
    ReviewUnavailableError,
)

router = APIRouter(tags=["feedback"])


def _export_record(snapshot: FeedbackExportSnapshot) -> FeedbackExportRecord:
    return FeedbackExportRecord.model_validate(snapshot, from_attributes=True)


@router.get(
    "/feedback/export",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {"application/x-ndjson": {}},
            "description": "One version-linked feedback record per JSON line.",
        }
    },
)
def export_feedback(
    settings: Annotated[Settings, Depends(get_settings)],
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
    updated_from: Annotated[datetime | None, Query()] = None,
    updated_to: Annotated[datetime | None, Query()] = None,
    review_pack_id: Annotated[UUID | None, Query()] = None,
) -> StreamingResponse:
    """Download tenant feedback for offline quality analysis as JSONL."""

    def content() -> Iterator[str]:
        with session_factory() as session:
            snapshots = FeedbackExportService(session).iter_snapshots(
                company_id=settings.default_company_id,
                updated_from=updated_from,
                updated_to=updated_to,
                review_pack_id=review_pack_id,
            )
            for snapshot in snapshots:
                yield _export_record(snapshot).model_dump_json() + "\n"

    try:
        FeedbackExportService.validate_filters(
            updated_from=updated_from,
            updated_to=updated_to,
        )
    except InvalidFeedbackExportFilter as error:
        raise ApiError(
            422,
            "FEEDBACK_EXPORT_FILTER_INVALID",
            "Feedback export filters are invalid.",
        ) from error

    return StreamingResponse(
        content(),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": 'attachment; filename="feedback-export.jsonl"'},
    )


@router.get("/feedback/metrics", response_model=FeedbackMetricsResponse)
def get_feedback_metrics(
    settings: Annotated[Settings, Depends(get_settings)],
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
    finding_created_from: Annotated[datetime | None, Query()] = None,
    finding_created_to: Annotated[datetime | None, Query()] = None,
    review_pack_id: Annotated[UUID | None, Query()] = None,
) -> FeedbackMetricsResponse:
    """Return operational feedback metrics for the current tenant."""

    try:
        with session_factory() as session:
            snapshot = FeedbackMetricsService(session).calculate(
                company_id=settings.default_company_id,
                finding_created_from=finding_created_from,
                finding_created_to=finding_created_to,
                review_pack_id=review_pack_id,
            )
    except InvalidFeedbackMetricsFilter as error:
        raise ApiError(
            422,
            "FEEDBACK_METRICS_FILTER_INVALID",
            "Feedback metrics filters are invalid.",
        ) from error
    return FeedbackMetricsResponse.model_validate(snapshot, from_attributes=True)


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
