"""Review Packs catalog and version authoring endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session, sessionmaker

from docreview_api.api.schemas.common import OpaqueId
from docreview_api.api.schemas.errors import ApiError
from docreview_api.api.schemas.review_packs import (
    ReviewPackContentResponse,
    ReviewPackListResponse,
    ReviewPackResponse,
    ReviewPackSourceResponse,
    ReviewPackVersionRequest,
    ReviewPackVersionResponse,
)
from docreview_api.config import Settings, get_settings
from docreview_api.db.dependencies import get_session_factory
from docreview_api.services.review_packs import (
    ReviewPackCatalogService,
    ReviewPackEditError,
)

# Отказ проверки — это не сбой сервера: пользователь прислал пакет, который
# ядро не принимает. Причина обязана дойти до редактора дословно, иначе
# человек не поймёт, какую строку чинить.
_EDIT_ERROR_STATUS: dict[str, int] = {
    "REVIEW_PACK_NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "REVIEW_PACK_VERSION_EXISTS": status.HTTP_409_CONFLICT,
    "REVIEW_PACK_VALIDATOR_UNAVAILABLE": status.HTTP_503_SERVICE_UNAVAILABLE,
    "REVIEW_PACK_VALIDATION_TIMEOUT": status.HTTP_504_GATEWAY_TIMEOUT,
}


def _edit_api_error(error: ReviewPackEditError) -> ApiError:
    return ApiError(
        _EDIT_ERROR_STATUS.get(error.code, status.HTTP_422_UNPROCESSABLE_CONTENT),
        error.code,
        error.message,
    )


def _catalog(
    settings: Settings, session_factory: sessionmaker[Session]
) -> ReviewPackCatalogService:
    return ReviewPackCatalogService(
        session_factory,
        review_packs_root=settings.review_packs_dir,
        analysis_executable=settings.analysis_executable,
    )

router = APIRouter(prefix="/review-packs", tags=["review-packs"])


@router.get("", response_model=ReviewPackListResponse)
def list_review_packs(
    settings: Annotated[Settings, Depends(get_settings)],
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
) -> ReviewPackListResponse:
    """List only active, valid server-side Review Packs for the current tenant."""

    snapshots = _catalog(settings, session_factory).list_available(
        company_id=settings.default_company_id
    )
    items = [
        ReviewPackResponse(
            review_pack_id=item.id,
            display_name=item.display_name,
            document_type=item.document_type,
            version=item.version,
            contents=[
                ReviewPackContentResponse(
                    key=part.key,
                    filename=part.filename,
                    description=part.description,
                    present=part.present,
                )
                for part in item.contents
            ],
            policy_bias=item.policy_bias,
        )
        for item in snapshots
    ]
    return ReviewPackListResponse(items=items, total=len(items))


@router.get("/{review_pack_id}/source", response_model=ReviewPackSourceResponse)
def read_review_pack_source(
    review_pack_id: OpaqueId,
    settings: Annotated[Settings, Depends(get_settings)],
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
) -> ReviewPackSourceResponse:
    """Отдать тексты настраиваемых файлов пакета для правки."""

    try:
        source = _catalog(settings, session_factory).read_source(
            company_id=settings.default_company_id, pack_id=review_pack_id
        )
    except ReviewPackEditError as error:
        raise _edit_api_error(error) from error
    return ReviewPackSourceResponse(
        review_pack_id=review_pack_id,
        pack_key=source.pack_key,
        version=source.version,
        display_name=source.display_name,
        files=source.files,
    )


@router.post(
    "/{review_pack_id}/versions",
    response_model=ReviewPackVersionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_review_pack_version(
    review_pack_id: OpaqueId,
    request: ReviewPackVersionRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
) -> ReviewPackVersionResponse:
    """Выпустить новую версию пакета с изменёнными файлами.

    Существующая версия не меняется никогда: на неё ссылаются прошлые
    проверки, и её версия — часть контракта результата. Пакет попадает
    в каталог только после того, как ядро подтвердило, что он валиден.
    """

    catalog = _catalog(settings, session_factory)
    try:
        source = catalog.read_source(
            company_id=settings.default_company_id, pack_id=review_pack_id
        )
        new_id = catalog.create_version(
            company_id=settings.default_company_id,
            pack_id=review_pack_id,
            version=request.version,
            files=request.files,
        )
    except ReviewPackEditError as error:
        raise _edit_api_error(error) from error
    return ReviewPackVersionResponse(
        review_pack_id=new_id,
        pack_key=source.pack_key,
        version=request.version,
    )
