from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from fastapi import Request
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from docreview_api.api.schemas.common import ApiModel, OpaqueId, UtcDateTime
from docreview_api.config import Settings
from docreview_api.main import create_app

ALLOWED_ORIGIN = "http://127.0.0.1:5173"


class ConventionFixture(ApiModel):
    resource_id: OpaqueId
    created_at: UtcDateTime


def test_transport_schema_serializes_opaque_uuid_and_normalizes_datetime_to_utc() -> None:
    resource_id = uuid4()
    value = ConventionFixture(
        resource_id=resource_id,
        created_at=datetime(2026, 9, 3, 15, 30, tzinfo=timezone(timedelta(hours=3))),
    )

    assert value.model_dump(mode="json") == {
        "resource_id": str(resource_id),
        "created_at": "2026-09-03T12:30:00.000Z",
    }
    assert isinstance(value.resource_id, UUID)
    assert value.created_at.tzinfo is UTC


def test_transport_schema_rejects_naive_datetime_and_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ConventionFixture(
            resource_id=uuid4(),
            created_at=datetime(2026, 9, 3, 12, 30),
            internal_storage_path="private/document.pdf",
        )


@pytest.mark.anyio
async def test_framework_validation_uses_common_error_envelope_without_input_value() -> None:
    app = create_app(Settings(environment="test", _env_file=None))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/documents", data={"document": "secret-content"})

    assert response.status_code == 422
    payload = response.json()
    assert payload["error"]["code"] == "REQUEST_VALIDATION_ERROR"
    assert payload["error"]["message"] == "Request validation failed."
    assert payload["error"]["details"]
    assert "secret-content" not in response.text


@pytest.mark.anyio
async def test_unknown_route_uses_common_error_envelope() -> None:
    app = create_app(Settings(environment="test", _env_file=None))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/missing")

    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "NOT_FOUND", "message": "Not Found", "details": []}
    }


@pytest.mark.anyio
async def test_unexpected_error_is_safe_and_uses_common_envelope() -> None:
    app = create_app(Settings(environment="test", _env_file=None))

    async def broken_endpoint() -> None:
        raise RuntimeError("private path and secret")

    app.add_api_route("/api/test-broken", broken_endpoint, include_in_schema=False)
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/test-broken")

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "INTERNAL_ERROR",
            "message": "An unexpected error occurred.",
            "details": [],
        }
    }
    assert "private path" not in response.text
    assert "secret" not in response.text
    assert len(response.headers["X-Correlation-ID"]) == 32


@pytest.mark.anyio
async def test_correlation_id_is_propagated_only_when_safe() -> None:
    app = create_app(Settings(environment="test", _env_file=None))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        propagated = await client.get(
            "/api/health", headers={"X-Correlation-ID": "review.ui:request-42"}
        )
        replaced = await client.get(
            "/api/health", headers={"X-Correlation-ID": "unsafe correlation value"}
        )

    assert propagated.headers["X-Correlation-ID"] == "review.ui:request-42"
    assert replaced.headers["X-Correlation-ID"] != "unsafe correlation value"
    assert len(replaced.headers["X-Correlation-ID"]) == 32


@pytest.mark.anyio
async def test_request_size_limit_rejects_declared_and_streamed_bodies() -> None:
    settings = Settings(
        environment="test",
        max_request_size_bytes=1024,
        rate_limit_requests=20,
        _env_file=None,
    )
    app = create_app(settings)

    async def consume_body(request: Request) -> dict[str, int]:
        body = await request.body()
        return {"size": len(body)}

    app.add_api_route("/api/test-body", consume_body, methods=["POST"], include_in_schema=False)

    async def streamed_body() -> AsyncIterator[bytes]:
        yield b"a" * 600
        yield b"b" * 600

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        declared = await client.post("/api/test-body", content=b"x" * 1025)
        streamed = await client.post("/api/test-body", content=streamed_body())

    expected_error = {
        "error": {
            "code": "REQUEST_TOO_LARGE",
            "message": "Request body exceeds the configured size limit.",
            "details": [],
        }
    }
    assert declared.status_code == 413
    assert streamed.status_code == 413
    assert declared.json() == streamed.json() == expected_error
    assert declared.headers["X-Correlation-ID"]
    assert streamed.headers["X-Correlation-ID"]


@pytest.mark.anyio
async def test_rate_limit_has_safe_envelope_retry_hint_and_correlation_id() -> None:
    settings = Settings(
        environment="test",
        rate_limit_requests=2,
        rate_limit_window_seconds=30,
        _env_file=None,
    )
    app = create_app(settings)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.get("/api/health", headers={"Origin": ALLOWED_ORIGIN})
        second = await client.get("/api/health", headers={"Origin": ALLOWED_ORIGIN})
        limited = await client.get("/api/health", headers={"Origin": ALLOWED_ORIGIN})

    assert first.status_code == second.status_code == 200
    assert first.headers["X-RateLimit-Remaining"] == "1"
    assert second.headers["X-RateLimit-Remaining"] == "0"
    assert limited.status_code == 429
    assert limited.json() == {
        "error": {
            "code": "RATE_LIMIT_EXCEEDED",
            "message": "Too many requests. Try again later.",
            "details": [],
        }
    }
    assert int(limited.headers["Retry-After"]) >= 1
    assert limited.headers["X-Correlation-ID"]
    assert limited.headers["Access-Control-Allow-Origin"] == ALLOWED_ORIGIN


@pytest.mark.anyio
async def test_cors_allows_configured_origin_and_rejects_other_origins() -> None:
    app = create_app(Settings(environment="test", _env_file=None))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        allowed = await client.options(
            "/api/findings/example/feedback",
            headers={
                "Origin": ALLOWED_ORIGIN,
                "Access-Control-Request-Method": "PUT",
                "Access-Control-Request-Headers": "X-Actor-Key,X-Correlation-ID,Content-Type",
            },
        )
        rejected = await client.get("/api/health", headers={"Origin": "https://untrusted.example"})

    assert allowed.status_code == 200
    assert allowed.headers["Access-Control-Allow-Origin"] == ALLOWED_ORIGIN
    assert "x-actor-key" in allowed.headers["Access-Control-Allow-Headers"].casefold()
    assert "x-correlation-id" in allowed.headers["Access-Control-Allow-Headers"].casefold()
    assert "Access-Control-Allow-Origin" not in rejected.headers


@pytest.mark.anyio
async def test_openapi_publishes_shared_error_and_uuid_conventions() -> None:
    app = create_app(Settings(environment="test", _env_file=None))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/openapi.json")

    schema = response.json()
    assert set(schema["paths"]) >= {"/api/health", "/api/documents"}
    operation = schema["paths"]["/api/documents"]["post"]
    assert operation["responses"]["422"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorEnvelope"
    }
    document_id = schema["components"]["schemas"]["DocumentUploadResponse"]["properties"][
        "document_id"
    ]
    assert document_id["format"] == "uuid"
    assert schema["components"]["schemas"]["ErrorEnvelope"]["additionalProperties"] is False
    assert operation["responses"]["429"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorEnvelope"
    }
