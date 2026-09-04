"""Transport schemas for analyst feedback on findings."""

from typing import Annotated

from pydantic import StringConstraints

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
