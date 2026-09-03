"""Retention policy and safe planning primitives without deletion side effects."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import PurePosixPath, PureWindowsPath
from uuid import UUID


class InvalidRetentionPolicy(ValueError):
    """Raised when a retention policy is unsafe or internally inconsistent."""


class InvalidTenantPurgePlan(ValueError):
    """Raised when a purge plan crosses a tenant or storage boundary."""


def _require_utc(value: datetime, field_name: str) -> None:
    if value.utcoffset() != timedelta(0):
        raise InvalidRetentionPolicy(f"{field_name} must be a timezone-aware UTC datetime")


@dataclass(frozen=True)
class RetentionPolicy:
    """Calculate eligibility dates; it deliberately cannot delete data."""

    document_retention_days: int = 90
    artifact_retention_days: int = 14
    automatic_deletion_enabled: bool = False

    def __post_init__(self) -> None:
        if not 1 <= self.document_retention_days <= 3650:
            raise InvalidRetentionPolicy("document retention must be between 1 and 3650 days")
        if not 1 <= self.artifact_retention_days <= 365:
            raise InvalidRetentionPolicy("artifact retention must be between 1 and 365 days")
        if self.automatic_deletion_enabled:
            raise InvalidRetentionPolicy("automatic deletion is forbidden in the MVP")

    def document_eligible_at(self, last_activity_at: datetime) -> datetime:
        """Return when an original file may be proposed for explicit cleanup."""

        _require_utc(last_activity_at, "last_activity_at")
        return last_activity_at + timedelta(days=self.document_retention_days)

    def artifacts_eligible_at(self, finished_at: datetime | None) -> datetime | None:
        """Return diagnostic-artifact eligibility; active jobs are never eligible."""

        if finished_at is None:
            return None
        _require_utc(finished_at, "finished_at")
        return finished_at + timedelta(days=self.artifact_retention_days)


MVP_RETENTION_POLICY = RetentionPolicy()


class PurgeResourceKind(StrEnum):
    """Kinds of data a future explicit tenant purge may address."""

    DOCUMENT_FILE = "document_file"
    DIAGNOSTIC_ARTIFACTS = "diagnostic_artifacts"
    DATABASE_RECORDS = "database_records"


@dataclass(frozen=True)
class TenantPurgeTarget:
    """One tenant-owned resource selected for an explicit purge plan."""

    company_id: UUID
    resource_kind: PurgeResourceKind
    resource_id: UUID
    storage_key: str | None = None

    def __post_init__(self) -> None:
        if self.resource_kind is PurgeResourceKind.DATABASE_RECORDS:
            if self.storage_key is not None:
                raise InvalidTenantPurgePlan("database targets cannot have a storage key")
            return
        if self.storage_key is None or not self.storage_key.strip():
            raise InvalidTenantPurgePlan("file targets require a storage key")
        if (
            "\\" in self.storage_key
            or PurePosixPath(self.storage_key).is_absolute()
            or PureWindowsPath(self.storage_key).is_absolute()
            or ".." in PurePosixPath(self.storage_key).parts
        ):
            raise InvalidTenantPurgePlan("storage key must be a safe relative POSIX path")


@dataclass(frozen=True)
class TenantPurgePlan:
    """Auditable, single-tenant description of a future explicit purge."""

    company_id: UUID
    targets: tuple[TenantPurgeTarget, ...]
    requested_by: str
    reason: str
    requested_at: datetime

    def __post_init__(self) -> None:
        if not self.targets:
            raise InvalidTenantPurgePlan("purge plan must contain at least one target")
        if any(target.company_id != self.company_id for target in self.targets):
            raise InvalidTenantPurgePlan("all purge targets must belong to one company")
        if not self.requested_by.strip():
            raise InvalidTenantPurgePlan("requested_by must not be empty")
        if not self.reason.strip():
            raise InvalidTenantPurgePlan("reason must not be empty")
        try:
            _require_utc(self.requested_at, "requested_at")
        except InvalidRetentionPolicy as error:
            raise InvalidTenantPurgePlan(str(error)) from error
