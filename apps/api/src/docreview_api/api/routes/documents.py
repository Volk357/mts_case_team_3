"""Document upload HTTP endpoint."""

from pathlib import Path
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session, sessionmaker

from docreview_api.api.schemas.common import OpaqueId
from docreview_api.api.schemas.documents import DocumentResponse, DocumentUploadResponse
from docreview_api.api.schemas.errors import ApiError
from docreview_api.config import Settings, get_settings
from docreview_api.db.dependencies import get_session_factory
from docreview_api.services.antivirus import (
    AntivirusRejectedError,
    AntivirusScanner,
    get_antivirus_scanner,
)
from docreview_api.services.document_storage import DocumentStorageService
from docreview_api.services.documents import (
    DocumentFileUnavailableError,
    DocumentQueryService,
    DocumentSnapshot,
    DocumentUnavailableError,
)
from docreview_api.services.upload_metrics import UploadMetrics, get_upload_metrics
from docreview_api.services.upload_validation import (
    DocumentFormatMismatchError,
    EmptyDocumentError,
    UnsafeFilenameError,
    UnsupportedDocumentTypeError,
    UploadTooLargeError,
)

router = APIRouter(prefix="/documents", tags=["documents"])


def _public_document(stored: DocumentSnapshot) -> DocumentResponse:
    return DocumentResponse(
        document_id=stored.id,
        filename=stored.filename,
        size_bytes=stored.size_bytes,
        media_type=stored.media_type,
        created_at=stored.created_at,
    )


def _validation_api_error(error: Exception) -> ApiError:
    if isinstance(error, UploadTooLargeError):
        status_code = status.HTTP_413_CONTENT_TOO_LARGE
        code = "DOCUMENT_TOO_LARGE"
        message = "Document exceeds the configured size limit."
    elif isinstance(error, UnsupportedDocumentTypeError):
        status_code = status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
        code = "DOCUMENT_TYPE_UNSUPPORTED"
        message = "Only PDF and DOCX documents are supported."
    elif isinstance(error, EmptyDocumentError):
        status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
        code = "DOCUMENT_EMPTY"
        message = "Document must not be empty."
    elif isinstance(error, UnsafeFilenameError):
        status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
        code = "DOCUMENT_FILENAME_INVALID"
        message = "Document filename is invalid."
    elif isinstance(error, AntivirusRejectedError):
        status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
        code = "DOCUMENT_REJECTED"
        message = "Document was rejected by the security check."
    else:
        status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
        code = "DOCUMENT_FORMAT_INVALID"
        message = "Document content does not match its declared format."
    return ApiError(status_code, code, message)


@router.post("", response_model=DocumentUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    document: Annotated[UploadFile, File(description="PDF or DOCX document")],
    settings: Annotated[Settings, Depends(get_settings)],
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
    antivirus_scanner: Annotated[AntivirusScanner, Depends(get_antivirus_scanner)],
    metrics: Annotated[UploadMetrics, Depends(get_upload_metrics)],
) -> DocumentUploadResponse:
    """Accept the multipart transport and return path-free public metadata.

    The service creates a database row only after an atomic filesystem move.
    """

    try:
        stored = await DocumentStorageService(
            settings.documents_dir,
            session_factory,
            antivirus_scanner=antivirus_scanner,
            metrics=metrics,
        ).store(
            document,
            max_size_bytes=settings.max_upload_size_bytes,
            company_id=settings.default_company_id,
            company_slug=settings.default_company_slug,
            company_name=settings.default_company_name,
        )
    except (
        DocumentFormatMismatchError,
        EmptyDocumentError,
        UnsafeFilenameError,
        UnsupportedDocumentTypeError,
        UploadTooLargeError,
        AntivirusRejectedError,
    ) as error:
        raise _validation_api_error(error) from error

    return DocumentUploadResponse(
        document_id=stored.id,
        filename=stored.original_filename,
        size_bytes=stored.size_bytes,
        media_type=stored.media_type,
    )


@router.get("/{document_id}", response_model=DocumentResponse)
def get_document(
    document_id: OpaqueId,
    settings: Annotated[Settings, Depends(get_settings)],
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
) -> DocumentResponse:
    """Return metadata only when both the tenant row and private file still exist."""

    try:
        snapshot = DocumentQueryService(
            session_factory,
            documents_root=settings.documents_dir,
        ).get(document_id, company_id=settings.default_company_id)
    except DocumentUnavailableError as error:
        raise ApiError(404, "DOCUMENT_NOT_FOUND", "Document was not found.") from error
    except DocumentFileUnavailableError as error:
        raise ApiError(
            409,
            "DOCUMENT_FILE_UNAVAILABLE",
            "Document content is temporarily unavailable.",
        ) from error
    return _public_document(snapshot)


@router.get(
    "/{document_id}/content",
    response_class=FileResponse,
    responses={
        200: {
            "content": {
                "application/pdf": {},
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document": {},
            },
            "description": "Original document content for the authenticated tenant.",
        }
    },
)
def get_document_content(
    document_id: OpaqueId,
    settings: Annotated[Settings, Depends(get_settings)],
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
) -> FileResponse:
    """Stream verified private content without exposing its storage location."""

    try:
        content = DocumentQueryService(
            session_factory,
            documents_root=settings.documents_dir,
        ).get_content(document_id, company_id=settings.default_company_id)
    except DocumentUnavailableError as error:
        raise ApiError(404, "DOCUMENT_NOT_FOUND", "Document was not found.") from error
    except DocumentFileUnavailableError as error:
        raise ApiError(
            409,
            "DOCUMENT_FILE_UNAVAILABLE",
            "Document content is temporarily unavailable.",
        ) from error

    fallback_name = f"document{Path(content.filename).suffix.lower()}"
    encoded_name = quote(content.filename)
    disposition = f"inline; filename=\"{fallback_name}\"; filename*=UTF-8''{encoded_name}"
    return FileResponse(
        content.path,
        media_type=content.media_type,
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": disposition,
            "X-Content-Type-Options": "nosniff",
        },
    )
