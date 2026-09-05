"""Read-only Review Packs catalog endpoint."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, sessionmaker

from docreview_api.api.schemas.review_packs import (
    ReviewPackListResponse,
    ReviewPackResponse,
)
from docreview_api.config import Settings, get_settings
from docreview_api.db.dependencies import get_session_factory
from docreview_api.services.review_packs import ReviewPackCatalogService

router = APIRouter(prefix="/review-packs", tags=["review-packs"])


@router.get("", response_model=ReviewPackListResponse)
def list_review_packs(
    settings: Annotated[Settings, Depends(get_settings)],
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
) -> ReviewPackListResponse:
    """List only active, valid server-side Review Packs for the current tenant."""

    snapshots = ReviewPackCatalogService(
        session_factory,
        review_packs_root=settings.review_packs_dir,
    ).list_available(company_id=settings.default_company_id)
    items = [
        ReviewPackResponse(
            review_pack_id=item.id,
            display_name=item.display_name,
            document_type=item.document_type,
            version=item.version,
            description=item.description,
        )
        for item in snapshots
    ]
    return ReviewPackListResponse(items=items, total=len(items))
