"""Transport schemas for system endpoints."""

from typing import Literal

from pydantic import Field

from docreview_api.api.schemas.common import ApiModel
from docreview_api.config import Environment


class HealthResponse(ApiModel):
    """Public health information without infrastructure details.

    `status` отражает реальную готовность, а не факт того, что процесс отвечает:
    как предполётная проверка перед демонстрацией константа бесполезна —
    она одинаково зелёная и когда база лежит, и когда воркер мёртв.
    Подробности инфраструктуры наружу не выходят: только имя зависимости и
    её состояние.
    """

    status: Literal["ok", "degraded"] = "ok"
    service: str
    environment: Environment
    version: str
    checks: dict[str, Literal["ok", "failed"]] = Field(default_factory=dict)
