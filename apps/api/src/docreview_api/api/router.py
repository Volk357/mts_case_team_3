"""Root API router."""

from fastapi import APIRouter

from docreview_api.api.routes.documents import router as documents_router
from docreview_api.api.routes.feedback import router as feedback_router
from docreview_api.api.routes.health import router as health_router
from docreview_api.api.routes.review_packs import router as review_packs_router
from docreview_api.api.routes.reviews import router as reviews_router
from docreview_api.api.schemas.errors import ERROR_RESPONSES

api_router = APIRouter(responses=ERROR_RESPONSES)
api_router.include_router(health_router)
api_router.include_router(documents_router)
api_router.include_router(feedback_router)
api_router.include_router(review_packs_router)
api_router.include_router(reviews_router)
