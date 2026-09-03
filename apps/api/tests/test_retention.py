from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import pytest

from docreview_api.services.retention import (
    InvalidRetentionPolicy,
    InvalidTenantPurgePlan,
    PurgeResourceKind,
    RetentionPolicy,
    TenantPurgePlan,
    TenantPurgeTarget,
)

UTC_TIME = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)


def test_default_retention_dates_are_calculated_without_side_effects() -> None:
    policy = RetentionPolicy()

    assert policy.document_eligible_at(UTC_TIME) == UTC_TIME + timedelta(days=90)
    assert policy.artifacts_eligible_at(UTC_TIME) == UTC_TIME + timedelta(days=14)
    assert policy.artifacts_eligible_at(None) is None
    assert policy.automatic_deletion_enabled is False


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"document_retention_days": 0}, "document retention"),
        ({"artifact_retention_days": 366}, "artifact retention"),
        ({"automatic_deletion_enabled": True}, "forbidden"),
    ],
)
def test_unsafe_retention_policy_is_rejected(kwargs: dict[str, object], message: str) -> None:
    with pytest.raises(InvalidRetentionPolicy, match=message):
        RetentionPolicy(**kwargs)  # type: ignore[arg-type]


def test_retention_anchors_must_be_utc() -> None:
    policy = RetentionPolicy()

    with pytest.raises(InvalidRetentionPolicy, match="UTC"):
        policy.document_eligible_at(datetime(2026, 9, 3, 12, 0))
    with pytest.raises(InvalidRetentionPolicy, match="UTC"):
        policy.artifacts_eligible_at(UTC_TIME.astimezone(timezone(timedelta(hours=3))))


def test_single_tenant_purge_plan_accepts_safe_targets() -> None:
    company_id = uuid4()
    document_id = uuid4()
    plan = TenantPurgePlan(
        company_id=company_id,
        targets=(
            TenantPurgeTarget(
                company_id=company_id,
                resource_kind=PurgeResourceKind.DOCUMENT_FILE,
                resource_id=document_id,
                storage_key=f"{company_id}/documents/{document_id}.pdf",
            ),
            TenantPurgeTarget(
                company_id=company_id,
                resource_kind=PurgeResourceKind.DATABASE_RECORDS,
                resource_id=document_id,
            ),
        ),
        requested_by="operator@example.test",
        reason="Tenant requested erasure",
        requested_at=UTC_TIME,
    )

    assert len(plan.targets) == 2


def test_purge_plan_rejects_cross_tenant_target() -> None:
    company_id = uuid4()
    target = TenantPurgeTarget(
        company_id=uuid4(),
        resource_kind=PurgeResourceKind.DATABASE_RECORDS,
        resource_id=uuid4(),
    )

    with pytest.raises(InvalidTenantPurgePlan, match="one company"):
        TenantPurgePlan(
            company_id=company_id,
            targets=(target,),
            requested_by="operator",
            reason="Tenant request",
            requested_at=UTC_TIME,
        )


@pytest.mark.parametrize("storage_key", ["../other/file.pdf", "/root/file.pdf", "C:\\file.pdf"])
def test_purge_target_rejects_unsafe_storage_key(storage_key: str) -> None:
    with pytest.raises(InvalidTenantPurgePlan, match="safe relative"):
        TenantPurgeTarget(
            company_id=uuid4(),
            resource_kind=PurgeResourceKind.DOCUMENT_FILE,
            resource_id=uuid4(),
            storage_key=storage_key,
        )


def test_purge_plan_requires_auditable_metadata() -> None:
    company_id = uuid4()
    target = TenantPurgeTarget(
        company_id=company_id,
        resource_kind=PurgeResourceKind.DATABASE_RECORDS,
        resource_id=uuid4(),
    )

    with pytest.raises(InvalidTenantPurgePlan, match="reason"):
        TenantPurgePlan(
            company_id=company_id,
            targets=(target,),
            requested_by="operator",
            reason=" ",
            requested_at=UTC_TIME,
        )
    with pytest.raises(InvalidTenantPurgePlan, match="UTC"):
        TenantPurgePlan(
            company_id=company_id,
            targets=(target,),
            requested_by="operator",
            reason="Tenant request",
            requested_at=datetime(2026, 9, 3, 12, 0),
        )
