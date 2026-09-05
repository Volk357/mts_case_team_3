from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from docreview_api.config import Settings
from docreview_api.db.base import Base
from docreview_api.db.session import create_database_engine
from docreview_api.main import create_app


def _settings(tmp_path: Path, database_url: str) -> Settings:
    return Settings(
        environment="test",
        database_url=database_url,
        worker_heartbeat_path=tmp_path / "worker-heartbeat",
        worker_poll_interval_seconds=1.0,
        worker_heartbeat_tolerance=3.0,
        _env_file=None,
    )


@pytest.mark.anyio
async def test_health_reports_working_dependencies(tmp_path: Path, database_url: str) -> None:
    """Здоровье — это готовность обслужить проверку, а не факт ответа процесса."""

    engine = create_database_engine(database_url)
    Base.metadata.create_all(engine)
    engine.dispose()
    settings = _settings(tmp_path, database_url)
    settings.worker_heartbeat_path.write_text(datetime.now(UTC).isoformat(), encoding="utf-8")

    async with AsyncClient(
        transport=ASGITransport(app=create_app(settings)), base_url="http://test"
    ) as client:
        response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "DocReview API",
        "environment": "test",
        "version": "0.1.0",
        "checks": {"database": "ok", "worker": "ok"},
    }


@pytest.mark.anyio
async def test_health_is_degraded_when_the_database_is_unusable(
    tmp_path: Path, database_url: str
) -> None:
    """Схемы нет — обслужить проверку нельзя, и health обязан это показать.
    Прежняя константа была зелёной и здесь, то есть перед демонстрацией не
    значила ничего."""

    settings = _settings(tmp_path, database_url)
    settings.worker_heartbeat_path.write_text(datetime.now(UTC).isoformat(), encoding="utf-8")

    async with AsyncClient(
        transport=ASGITransport(app=create_app(settings)), base_url="http://test"
    ) as client:
        response = await client.get("/api/health")

    body = response.json()
    assert response.status_code == 200  # недоступная база — это degraded, не 500
    assert body["status"] == "degraded"
    assert body["checks"]["database"] == "failed"


@pytest.mark.anyio
async def test_health_is_degraded_when_the_worker_is_silent(
    tmp_path: Path, database_url: str
) -> None:
    """Главный случай: очередь пуста, а воркер мёртв.

    По длине очереди это состояние неотличимо от простоя — именно поэтому
    живость определяется отметкой самого воркера, а не числом задач.
    """

    engine = create_database_engine(database_url)
    Base.metadata.create_all(engine)
    engine.dispose()
    settings = _settings(tmp_path, database_url)
    stale = datetime.now(UTC) - timedelta(minutes=5)
    settings.worker_heartbeat_path.write_text(stale.isoformat(), encoding="utf-8")

    async with AsyncClient(
        transport=ASGITransport(app=create_app(settings)), base_url="http://test"
    ) as client:
        response = await client.get("/api/health")

    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["worker"] == "failed"
    assert body["checks"]["database"] == "ok"


@pytest.mark.anyio
async def test_health_is_degraded_when_the_worker_never_started(
    tmp_path: Path, database_url: str
) -> None:
    """Отметки нет вовсе — воркер не запускался."""

    engine = create_database_engine(database_url)
    Base.metadata.create_all(engine)
    engine.dispose()

    async with AsyncClient(
        transport=ASGITransport(app=create_app(_settings(tmp_path, database_url))),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/health")

    assert response.json()["checks"]["worker"] == "failed"


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
