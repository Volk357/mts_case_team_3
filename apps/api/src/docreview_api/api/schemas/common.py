"""Shared transport-only types and serialization conventions."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, PlainSerializer


class ApiModel(BaseModel):
    """Strict public schema; ORM entities are mapped explicitly at API boundaries."""

    model_config = ConfigDict(extra="forbid")


OpaqueId = Annotated[
    UUID,
    Field(description="Opaque resource identifier. Clients must not infer meaning from it."),
]


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must include a timezone")
    return value.astimezone(UTC)


def _serialize_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


UtcDateTime = Annotated[
    datetime,
    AfterValidator(_as_utc),
    PlainSerializer(_serialize_utc, return_type=str, when_used="json"),
    Field(description="UTC timestamp in ISO 8601 format", examples=["2026-09-03T12:00:00.000Z"]),
]
