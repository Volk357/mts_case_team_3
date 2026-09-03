"""Transport schemas for the Documents API."""

from docreview_api.api.schemas.common import ApiModel, OpaqueId, UtcDateTime


class DocumentUploadResponse(ApiModel):
    """Public metadata returned after accepting a document upload."""

    document_id: OpaqueId
    filename: str
    size_bytes: int
    media_type: str


class DocumentResponse(DocumentUploadResponse):
    """Verified public metadata for one stored document."""

    created_at: UtcDateTime
