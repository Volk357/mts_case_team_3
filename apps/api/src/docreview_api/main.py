"""FastAPI application factory and default ASGI application."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from docreview_api import __version__
from docreview_api.api.exception_handlers import register_exception_handlers
from docreview_api.api.middleware import (
    CorrelationIdMiddleware,
    RateLimitMiddleware,
    RequestSizeLimitMiddleware,
)
from docreview_api.api.router import api_router
from docreview_api.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the API application, optionally with explicit test settings."""

    resolved_settings = settings or get_settings()
    application = FastAPI(
        title=resolved_settings.app_name,
        version=__version__,
        docs_url=f"{resolved_settings.api_prefix}/docs",
        openapi_url=f"{resolved_settings.api_prefix}/openapi.json",
    )
    if settings is not None:

        def settings_provider() -> Settings:
            return resolved_settings

        application.dependency_overrides[get_settings] = settings_provider
    application.add_middleware(
        RateLimitMiddleware,
        requests_per_window=resolved_settings.rate_limit_requests,
        window_seconds=resolved_settings.rate_limit_window_seconds,
    )
    application.add_middleware(
        RequestSizeLimitMiddleware,
        max_bytes=resolved_settings.max_request_size_bytes,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved_settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Accept",
            "Authorization",
            "Content-Type",
            "Idempotency-Key",
            "X-Actor-Key",
            "X-Correlation-ID",
        ],
        expose_headers=[
            "Location",
            "Retry-After",
            "X-Correlation-ID",
            "X-RateLimit-Limit",
            "X-RateLimit-Remaining",
        ],
    )
    application.add_middleware(CorrelationIdMiddleware)
    register_exception_handlers(application)
    application.include_router(api_router, prefix=resolved_settings.api_prefix)
    return application


app = create_app()
