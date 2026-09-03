"""Root API router."""

from fastapi import APIRouter

from docreview_api.api.routes.documents import router as documents_router
from docreview_api.api.routes.health import router as health_router
from docreview_api.api.routes.reviews import router as reviews_router
from docreview_api.api.schemas.errors import ERROR_RESPONSES

api_router = APIRouter(responses=ERROR_RESPONSES)
api_router.include_router(health_router)
api_router.include_router(documents_router)
api_router.include_router(reviews_router)
