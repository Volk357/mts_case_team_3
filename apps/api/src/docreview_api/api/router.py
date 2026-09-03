"""Root API router."""

from fastapi import APIRouter

from docreview_api.api.routes.health import router as health_router

api_router = APIRouter()
api_router.include_router(health_router)
