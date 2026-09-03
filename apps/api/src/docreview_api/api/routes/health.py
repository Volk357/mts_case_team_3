"""Service health endpoint."""

from typing import Annotated

from fastapi import APIRouter, Depends

from docreview_api import __version__
from docreview_api.api.schemas.system import HealthResponse
from docreview_api.config import Settings, get_settings

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse)
def health(settings: Annotated[Settings, Depends(get_settings)]) -> HealthResponse:
    """Report that the API process is ready to serve requests."""

    return HealthResponse(
        service=settings.app_name,
        environment=settings.environment,
        version=__version__,
    )
