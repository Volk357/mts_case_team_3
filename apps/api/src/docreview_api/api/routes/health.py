"""Service health endpoint."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from docreview_api import __version__
from docreview_api.config import Environment, Settings, get_settings

router = APIRouter(tags=["system"])


class HealthResponse(BaseModel):
    """Public health information without infrastructure details."""

    status: Literal["ok"] = "ok"
    service: str
    environment: Environment
    version: str


@router.get("/health", response_model=HealthResponse)
def health(settings: Annotated[Settings, Depends(get_settings)]) -> HealthResponse:
    """Report that the API process is ready to serve requests."""

    return HealthResponse(
        service=settings.app_name,
        environment=settings.environment,
        version=__version__,
    )
