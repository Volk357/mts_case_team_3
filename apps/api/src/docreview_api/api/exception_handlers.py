"""Application-wide conversion of exceptions into the public error envelope."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from docreview_api.api.middleware import RequestBodyTooLarge
from docreview_api.api.schemas.errors import ApiError, ErrorBody, ErrorEnvelope, ErrorItem

LOGGER = logging.getLogger(__name__)


def _response(
    status_code: int,
    code: str,
    message: str,
    *,
    details: tuple[ErrorItem, ...] = (),
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    payload = ErrorEnvelope(
        error=ErrorBody(code=code, message=message, details=details)
    ).model_dump(mode="json")
    return JSONResponse(status_code=status_code, content=payload, headers=headers)


async def api_error_handler(_: Request, error: ApiError) -> JSONResponse:
    return _response(
        error.status_code,
        error.code,
        error.message,
        headers=error.headers,
    )


async def http_error_handler(_: Request, error: HTTPException) -> JSONResponse:
    return _response(
        error.status_code,
        _http_error_code(error.status_code),
        _http_error_message(error.status_code),
        headers=error.headers,
    )


async def validation_error_handler(_: Request, error: RequestValidationError) -> JSONResponse:
    details = tuple(
        ErrorItem(
            location=tuple(str(part) for part in item.get("loc", ())),
            reason=_safe_validation_reason(item),
        )
        for item in error.errors()
    )
    return _response(
        422,
        "REQUEST_VALIDATION_ERROR",
        "Request validation failed.",
        details=details,
    )


async def unexpected_error_handler(request: Request, error: Exception) -> JSONResponse:
    correlation_id = getattr(request.state, "correlation_id", "unassigned")
    LOGGER.exception(
        "Unhandled API error for %s %s correlation_id=%s",
        request.method,
        request.url.path,
        correlation_id,
        exc_info=(type(error), error, error.__traceback__),
    )
    return _response(
        500,
        "INTERNAL_ERROR",
        "An unexpected error occurred.",
        headers={"X-Correlation-ID": correlation_id},
    )


async def request_body_too_large_handler(_: Request, __: Exception) -> JSONResponse:
    return _response(
        413,
        "REQUEST_TOO_LARGE",
        "Request body exceeds the configured size limit.",
    )


def register_exception_handlers(application: FastAPI) -> None:
    application.add_exception_handler(ApiError, api_error_handler)  # type: ignore[arg-type]
    application.add_exception_handler(RequestBodyTooLarge, request_body_too_large_handler)
    application.add_exception_handler(HTTPException, http_error_handler)  # type: ignore[arg-type]
    application.add_exception_handler(
        RequestValidationError,
        validation_error_handler,  # type: ignore[arg-type]
    )
    application.add_exception_handler(Exception, unexpected_error_handler)


def _safe_validation_reason(item: dict[str, Any]) -> str:
    return {
        "missing": "Field required",
        "json_invalid": "Invalid JSON",
    }.get(str(item.get("type")), "Invalid value")


def _http_error_code(status_code: int) -> str:
    return {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        405: "METHOD_NOT_ALLOWED",
        409: "CONFLICT",
        413: "PAYLOAD_TOO_LARGE",
        429: "RATE_LIMIT_EXCEEDED",
        415: "UNSUPPORTED_MEDIA_TYPE",
        422: "UNPROCESSABLE_CONTENT",
    }.get(status_code, "HTTP_ERROR")


def _http_error_message(status_code: int) -> str:
    return {
        400: "Bad Request",
        401: "Unauthorized",
        403: "Forbidden",
        404: "Not Found",
        405: "Method Not Allowed",
        409: "Conflict",
        413: "Payload Too Large",
        429: "Too Many Requests",
        415: "Unsupported Media Type",
        422: "Unprocessable Content",
    }.get(status_code, "Request failed.")
