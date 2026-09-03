from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from docreview_api.api.schemas.common import ApiModel, OpaqueId, UtcDateTime
from docreview_api.config import Settings
from docreview_api.main import create_app


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
