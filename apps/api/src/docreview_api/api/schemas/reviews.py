"""Transport-only schemas for the Reviews API."""

from typing import Any, Literal

from pydantic import ConfigDict, Field

from docreview_api.api.schemas.common import ApiModel, OpaqueId, UtcDateTime

ReviewStatus = Literal["queued", "running", "completed", "failed", "timed_out", "cancelled"]
ReviewStage = Literal["waiting", "analysis", "result_ready", "finished"]


class ReviewCreateRequest(ApiModel):
    document_id: OpaqueId
    review_pack_id: OpaqueId


class ReviewPublicError(ApiModel):
    code: str
    message: str
    retriable: bool


class ReviewResponse(ApiModel):
    review_id: OpaqueId
    document_id: OpaqueId
    review_pack_id: OpaqueId
    status: ReviewStatus
    stage: ReviewStage
    queued_at: UtcDateTime
    started_at: UtcDateTime | None
    finished_at: UtcDateTime | None
    poll_after_ms: int | None = Field(default=None, ge=1000)
    error: ReviewPublicError | None = None


class FindingLocation(ApiModel):
    page: int | None
    section_path: list[str]
    block_id: str
    table: str | None = None
    row: int | str | None = None
    column: int | str | None = None
    bbox: dict[str, Any] | None = None

    model_config = ConfigDict(extra="allow")


class FindingResponse(ApiModel):
    finding_id: OpaqueId
    ordinal: int
    defect_id: str
    severity: Literal["critical", "high", "medium", "low"]
    confidence: float = Field(ge=0, le=1)
    location: FindingLocation
    quote: str
    problem: str
    clarification: str
    # Public, closed detection-layer vocabulary. Internal analyzer names from
    # `detected_by` must never cross the API boundary.
    detection_layer: Literal["rule", "model", "mixed"] | None = None


class ReviewWarning(ApiModel):
    code: str | None
    message: str


class FindingsResponse(ApiModel):
    review_id: OpaqueId
    items: list[FindingResponse]
    total: int = Field(ge=0)
    warnings: list[ReviewWarning]


class ReviewListItemResponse(ApiModel):
    """Строка истории проверок.

    Имя файла нужно, чтобы человек узнал свою проверку в списке: идентификатор
    для этого бесполезен. Диагностики ошибки здесь нет — в списке достаточно
    статуса, подробности видны на самой проверке.
    """

    review_id: OpaqueId
    document_id: OpaqueId
    document_filename: str
    status: ReviewStatus
    queued_at: UtcDateTime
    finished_at: UtcDateTime | None
    findings_count: int = Field(ge=0)


class ReviewListResponse(ApiModel):
    items: list[ReviewListItemResponse]
    total: int = Field(ge=0)
