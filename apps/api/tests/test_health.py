import pytest
from httpx import ASGITransport, AsyncClient

from docreview_api.config import Settings
from docreview_api.main import create_app


@pytest.mark.anyio
async def test_health_endpoint() -> None:
    app = create_app(Settings(environment="test", _env_file=None))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "DocReview API",
        "environment": "test",
        "version": "0.1.0",
    }


@pytest.mark.anyio
async def test_openapi_is_served_under_api_prefix() -> None:
    app = create_app(Settings(environment="test", _env_file=None))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "DocReview API"


@pytest.mark.anyio
async def test_cors_allows_only_configured_origin() -> None:
    app = create_app(
        Settings(
            environment="test",
            cors_origins=("https://review.example",),
            _env_file=None,
        )
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        allowed = await client.options(
            "/api/health",
            headers={
                "Origin": "https://review.example",
                "Access-Control-Request-Method": "GET",
            },
        )
        rejected = await client.options(
            "/api/health",
            headers={
                "Origin": "https://untrusted.example",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "https://review.example"
    assert "access-control-allow-origin" not in rejected.headers
