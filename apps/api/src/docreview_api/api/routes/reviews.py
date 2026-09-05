"""Asynchronous review creation, polling, and findings endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Response, status
from sqlalchemy.orm import Session, sessionmaker

from docreview_api.api.schemas.common import OpaqueId
from docreview_api.api.schemas.errors import ApiError
from docreview_api.api.schemas.reviews import (
    FindingResponse,
    FindingsResponse,
    ReviewCreateRequest,
    ReviewListItemResponse,
    ReviewListResponse,
    ReviewPublicError,
    ReviewResponse,
    ReviewWarning,
    ReviewWarningResponse,
)
from docreview_api.config import Settings, get_settings
from docreview_api.db.dependencies import get_session_factory
from docreview_api.models.review_job_state import (
    FAILED_STATUSES,
    TERMINAL_STATUSES,
    ReviewJobStatus,
)
from docreview_api.services.review_jobs import (
    IdempotencyConflictError,
    ReviewJobCreationError,
    ReviewJobDocumentUnavailableError,
    ReviewJobNotRetryableError,
    ReviewJobPackUnavailableError,
    ReviewJobResourceUnavailableError,
    ReviewJobService,
)
from docreview_api.services.reviews import (
    ReviewListItem,
    ReviewQueryService,
    ReviewSnapshot,
    ReviewUnavailableError,
)

router = APIRouter(prefix="/reviews", tags=["reviews"])


def _stage(job_status: ReviewJobStatus) -> str:
    if job_status is ReviewJobStatus.QUEUED:
        return "waiting"
    if job_status is ReviewJobStatus.RUNNING:
        return "analysis"
    if job_status is ReviewJobStatus.COMPLETED:
        return "result_ready"
    return "finished"


def _public_review(snapshot: ReviewSnapshot, poll_after_ms: int) -> ReviewResponse:
    failure = None
    if snapshot.status in FAILED_STATUSES:
        failure = ReviewPublicError(
            code=snapshot.error_code or "REVIEW_FAILED",
            message=snapshot.user_error_message or "Review could not be completed.",
            retriable=bool(snapshot.error_retriable),
        )
    return ReviewResponse(
        review_id=snapshot.id,
        document_id=snapshot.document_id,
        review_pack_id=snapshot.review_pack_id,
        status=snapshot.status.value,
        stage=_stage(snapshot.status),
        queued_at=snapshot.queued_at,
        started_at=snapshot.started_at,
        finished_at=snapshot.finished_at,
        poll_after_ms=None if snapshot.status in TERMINAL_STATUSES else poll_after_ms,
        error=failure,
        warnings=[ReviewWarningResponse(code=w.code, message=w.message) for w in snapshot.warnings],
    )


def _set_poll_header(response: Response, review: ReviewResponse, poll_seconds: int) -> None:
    if review.poll_after_ms is not None:
        response.headers["Retry-After"] = str(poll_seconds)


@router.post("", response_model=ReviewResponse, status_code=status.HTTP_202_ACCEPTED)
def create_review(
    request: ReviewCreateRequest,
    response: Response,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=255),
    ],
    settings: Annotated[Settings, Depends(get_settings)],
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
) -> ReviewResponse:
    """Persist a queued job and return immediately; a worker runs it separately."""

    try:
        with session_factory.begin() as session:
            result = ReviewJobService(session).create(
                company_id=settings.default_company_id,
                document_id=request.document_id,
                review_pack_reference_id=request.review_pack_id,
                idempotency_key=idempotency_key,
            )
            review_id = result.job.id
    except ReviewJobDocumentUnavailableError as error:
        raise ApiError(404, "DOCUMENT_NOT_FOUND", "Document was not found.") from error
    except ReviewJobPackUnavailableError as error:
        raise ApiError(404, "REVIEW_PACK_NOT_FOUND", "Review Pack was not found.") from error
    except IdempotencyConflictError as error:
        raise ApiError(
            409,
            "IDEMPOTENCY_CONFLICT",
            "Idempotency key was already used for another review request.",
        ) from error
    except ReviewJobResourceUnavailableError as error:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "Requested resource was not found.") from error
    except ReviewJobCreationError as error:
        raise ApiError(422, "REVIEW_REQUEST_INVALID", "Review request is invalid.") from error

    snapshot = ReviewQueryService(session_factory).get(
        review_id, company_id=settings.default_company_id
    )
    public = _public_review(snapshot, settings.review_poll_interval_seconds * 1000)
    response.headers["Location"] = f"{settings.api_prefix}/reviews/{review_id}"
    _set_poll_header(response, public, settings.review_poll_interval_seconds)
    return public


@router.post(
    "/{review_id}/retry",
    response_model=ReviewResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_review(
    review_id: OpaqueId,
    response: Response,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=255),
    ],
    settings: Annotated[Settings, Depends(get_settings)],
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
) -> ReviewResponse:
    """Queue a new run linked to a terminal retriable failure."""

    try:
        with session_factory.begin() as session:
            result = ReviewJobService(session).retry(
                review_id,
                company_id=settings.default_company_id,
                idempotency_key=idempotency_key,
            )
            retried_review_id = result.job.id
    except ReviewJobNotRetryableError as error:
        raise ApiError(
            409,
            "REVIEW_NOT_RETRYABLE",
            "Only a retriable failed review can be started again.",
        ) from error
    except IdempotencyConflictError as error:
        raise ApiError(
            409,
            "IDEMPOTENCY_CONFLICT",
            "Idempotency key was already used for another review request.",
        ) from error
    except ReviewJobResourceUnavailableError as error:
        raise ApiError(404, "REVIEW_NOT_FOUND", "Review was not found.") from error
    except ReviewJobCreationError as error:
        raise ApiError(422, "REVIEW_REQUEST_INVALID", "Review request is invalid.") from error

    snapshot = ReviewQueryService(session_factory).get(
        retried_review_id, company_id=settings.default_company_id
    )
    public = _public_review(snapshot, settings.review_poll_interval_seconds * 1000)
    response.headers["Location"] = f"{settings.api_prefix}/reviews/{retried_review_id}"
    _set_poll_header(response, public, settings.review_poll_interval_seconds)
    return public


def _public_list_item(item: ReviewListItem) -> ReviewListItemResponse:
    return ReviewListItemResponse(
        review_id=item.id,
        document_id=item.document_id,
        document_filename=item.document_filename,
        review_pack_id=item.review_pack_id,
        review_pack_name=item.review_pack_name,
        review_pack_version=item.review_pack_version,
        status=item.status.value,
        queued_at=item.queued_at,
        finished_at=item.finished_at,
        findings_count=item.findings_count,
    )


@router.get("", response_model=ReviewListResponse)
def list_reviews(
    settings: Annotated[Settings, Depends(get_settings)],
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> ReviewListResponse:
    """Return recent reviews of the tenant, newest first."""

    items = ReviewQueryService(session_factory).list_recent(
        company_id=settings.default_company_id, limit=limit
    )
    return ReviewListResponse(items=[_public_list_item(item) for item in items], total=len(items))


@router.get("/{review_id}", response_model=ReviewResponse)
def get_review(
    review_id: OpaqueId,
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
) -> ReviewResponse:
    """Return a small public lifecycle snapshot suitable for polling."""

    try:
        snapshot = ReviewQueryService(session_factory).get(
            review_id, company_id=settings.default_company_id
        )
    except ReviewUnavailableError as error:
        raise ApiError(404, "REVIEW_NOT_FOUND", "Review was not found.") from error
    public = _public_review(snapshot, settings.review_poll_interval_seconds * 1000)
    _set_poll_header(response, public, settings.review_poll_interval_seconds)
    return public


@router.get("/{review_id}/findings", response_model=FindingsResponse)
def get_review_findings(
    review_id: OpaqueId,
    settings: Annotated[Settings, Depends(get_settings)],
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
) -> FindingsResponse:
    """Return ordered public findings, or an empty list while analysis is pending."""

    try:
        result = ReviewQueryService(session_factory).get_findings(
            review_id, company_id=settings.default_company_id
        )
    except ReviewUnavailableError as error:
        raise ApiError(404, "REVIEW_NOT_FOUND", "Review was not found.") from error
    items = [
        FindingResponse(
            finding_id=item.id,
            ordinal=item.ordinal,
            defect_id=item.defect_id,
            severity=item.severity,
            confidence=item.confidence,
            location=item.location,
            quote=item.quote,
            problem=item.problem,
            clarification=item.clarification,
            detection_layer=item.detection_layer,
        )
        for item in result.items
    ]
    warnings = [ReviewWarning(code=item.code, message=item.message) for item in result.warnings]
    return FindingsResponse(
        review_id=review_id,
        items=items,
        total=len(items),
        warnings=warnings,
    )
