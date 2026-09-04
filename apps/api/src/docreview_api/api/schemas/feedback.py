"""Transport schemas for analyst feedback and quality export."""

from typing import Annotated, Any

from pydantic import Field, StringConstraints

from docreview_api.api.schemas.common import ApiModel, OpaqueId, UtcDateTime
from docreview_api.models.finding_feedback import FeedbackDecision

FeedbackComment = Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)]


class FeedbackUpsertRequest(ApiModel):
    decision: FeedbackDecision
    comment: FeedbackComment | None = None


class FeedbackResponse(ApiModel):
    feedback_id: OpaqueId
    finding_id: OpaqueId
    decision: FeedbackDecision
    comment: str | None
    created_at: UtcDateTime
    updated_at: UtcDateTime


class FeedbackListResponse(ApiModel):
    review_id: OpaqueId
    items: list[FeedbackResponse]
    total: int = Field(ge=0)


class FeedbackExportRecord(ApiModel):
    run_id: str
    review_id: OpaqueId
    finding_id: OpaqueId
    core_finding_id: str
    ordinal: int = Field(ge=0)
    defect_id: str
    severity: str
    confidence: float = Field(ge=0, le=1)
    location: dict[str, Any]
    quote: str
    problem: str
    clarification: str
    review_pack_reference_id: OpaqueId
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
    feedback_created_at: UtcDateTime
    feedback_updated_at: UtcDateTime
