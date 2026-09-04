"""Stable public error envelope shared by every API endpoint."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from docreview_api.api.schemas.common import ApiModel


class ErrorItem(ApiModel):
    location: tuple[str, ...] = Field(default_factory=tuple)
    reason: str


class ErrorBody(ApiModel):
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    message: str
    details: tuple[ErrorItem, ...] = Field(default_factory=tuple)


class ErrorEnvelope(ApiModel):
    error: ErrorBody


class ApiError(Exception):
    """Known transport error with a safe public code and message."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.headers = headers


ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": ErrorEnvelope, "description": "Invalid request"},
    404: {"model": ErrorEnvelope, "description": "Resource not found"},
    409: {"model": ErrorEnvelope, "description": "Resource state conflict"},
    413: {"model": ErrorEnvelope, "description": "Request payload is too large"},
    415: {"model": ErrorEnvelope, "description": "Unsupported media type"},
    422: {"model": ErrorEnvelope, "description": "Request validation failed"},
    429: {"model": ErrorEnvelope, "description": "Rate limit exceeded"},
    500: {"model": ErrorEnvelope, "description": "Internal server error"},
}
