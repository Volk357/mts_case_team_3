"""Public transport schemas for the Review Packs catalog."""

from pydantic import Field

from docreview_api.api.schemas.common import ApiModel, OpaqueId


class ReviewPackResponse(ApiModel):
    """Public metadata for one server-approved Review Pack version."""

    review_pack_id: OpaqueId
    display_name: str = Field(min_length=1, max_length=255)
    document_type: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=2000)


class ReviewPackListResponse(ApiModel):
    """Stable envelope for the tenant-visible Review Pack catalog."""

    items: list[ReviewPackResponse]
    total: int = Field(ge=0)
