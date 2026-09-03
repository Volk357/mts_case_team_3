"""Transport schemas for system endpoints."""

from typing import Literal

from docreview_api.api.schemas.common import ApiModel
from docreview_api.config import Environment


class HealthResponse(ApiModel):
    """Public health information without infrastructure details."""

    status: Literal["ok"] = "ok"
    service: str
    environment: Environment
    version: str
