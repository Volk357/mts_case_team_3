import asyncio
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from docreview_api.config import Settings
from docreview_api.db.base import Base
from docreview_api.db.models import (
    CompanyModel,
    DocumentModel,
    FindingModel,
    ReviewJobModel,
    ReviewPackReferenceModel,
)
from docreview_api.db.session import create_database_engine, create_session_factory
from docreview_api.main import create_app
from docreview_api.models.review_job_state import ReviewJobStatus


@pytest.fixture
def review_resources(tmp_path: Path) -> tuple[Settings, UUID, UUID]:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'reviews.db').as_posix()}",
        documents_dir=tmp_path / "documents",
        review_poll_interval_seconds=3,
        _env_file=None,
    )
    engine = create_database_engine(settings.database_url)
    Base.metadata.create_all(engine)
    sessions = create_session_factory(engine)
    with sessions.begin() as session:
        company = CompanyModel(
            id=settings.default_company_id,
            slug=settings.default_company_slug,
            display_name=settings.default_company_name,
        )
        document = DocumentModel(
            company_id=company.id,
            original_filename="requirements.pdf",
            media_type="application/pdf",
            size_bytes=10,
            sha256="a" * 64,
            storage_key="local/document.pdf",
        )
        pack = ReviewPackReferenceModel(
            company_id=company.id,
            pack_key="requirements",
            version="1.0",
            display_name="Requirements",
            locator="review-packs/requirements/1.0",
        )
        session.add_all([company, document, pack])
        session.flush()
        document_id, pack_id = document.id, pack.id
    engine.dispose()
    return settings, document_id, pack_id


@pytest.mark.anyio
async def test_create_is_async_idempotent_and_pollable(
    review_resources: tuple[Settings, UUID, UUID],
) -> None:
    settings, document_id, pack_id = review_resources
    app = create_app(settings)
    request = {"document_id": str(document_id), "review_pack_id": str(pack_id)}
    headers = {"Idempotency-Key": "upload-submit-1"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/api/reviews", json=request, headers=headers)
        repeated = await client.post("/api/reviews", json=request, headers=headers)
        polled = await client.get(created.headers["Location"])

    assert created.status_code == 202
    assert repeated.status_code == 202
    assert created.json()["review_id"] == repeated.json()["review_id"]
    assert created.headers["Retry-After"] == "3"
    assert polled.headers["Retry-After"] == "3"
    assert polled.json()["status"] == "queued"
    assert polled.json()["stage"] == "waiting"
    assert polled.json()["poll_after_ms"] == 3000
    assert polled.json()["queued_at"].endswith("Z")
    assert set(polled.json()) == {
        "review_id",
        "document_id",
        "review_pack_id",
        "status",
        "stage",
        "queued_at",
        "started_at",
        "finished_at",
        "poll_after_ms",
        "error",
    }

    engine = create_database_engine(settings.database_url)
    sessions = create_session_factory(engine)
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(ReviewJobModel)) == 1
    engine.dispose()


@pytest.mark.anyio
async def test_concurrent_polling_returns_consistent_public_snapshots(
    review_resources: tuple[Settings, UUID, UUID],
) -> None:
    settings, document_id, pack_id = review_resources
    app = create_app(settings)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/api/reviews",
            json={"document_id": str(document_id), "review_pack_id": str(pack_id)},
            headers={"Idempotency-Key": "concurrent-polling"},
        )
        location = created.headers["Location"]
        responses = await asyncio.gather(*(client.get(location) for _ in range(16)))

    assert {response.status_code for response in responses} == {200}
    assert {response.headers["Retry-After"] for response in responses} == {"3"}
    assert {response.json()["review_id"] for response in responses} == {created.json()["review_id"]}
    assert {response.json()["status"] for response in responses} == {"queued"}
    assert {response.json()["stage"] for response in responses} == {"waiting"}
    assert {response.json()["poll_after_ms"] for response in responses} == {3000}


@pytest.mark.anyio
async def test_create_distinguishes_missing_resources_and_idempotency_conflicts(
    review_resources: tuple[Settings, UUID, UUID],
) -> None:
    settings, document_id, pack_id = review_resources
    app = create_app(settings)
    headers = {"Idempotency-Key": "same-key"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        missing_document = await client.post(
            "/api/reviews",
            json={"document_id": str(uuid4()), "review_pack_id": str(pack_id)},
            headers={"Idempotency-Key": "missing-document"},
        )
        missing_pack = await client.post(
            "/api/reviews",
            json={"document_id": str(document_id), "review_pack_id": str(uuid4())},
            headers={"Idempotency-Key": "missing-pack"},
        )
        first = await client.post(
            "/api/reviews",
            json={"document_id": str(document_id), "review_pack_id": str(pack_id)},
            headers=headers,
        )
        conflict = await client.post(
            "/api/reviews",
            json={"document_id": str(uuid4()), "review_pack_id": str(pack_id)},
            headers=headers,
        )

    assert missing_document.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"
    assert missing_pack.json()["error"]["code"] == "REVIEW_PACK_NOT_FOUND"
    assert first.status_code == 202
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


@pytest.mark.anyio
async def test_status_hides_diagnostics_and_findings_are_public_and_ordered(
    review_resources: tuple[Settings, UUID, UUID],
) -> None:
    settings, document_id, pack_id = review_resources
    app = create_app(settings)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/api/reviews",
            json={"document_id": str(document_id), "review_pack_id": str(pack_id)},
            headers={"Idempotency-Key": "completed-review"},
        )
    review_id = UUID(created.json()["review_id"])

    engine = create_database_engine(settings.database_url)
    sessions = create_session_factory(engine)
    now = datetime(2026, 9, 3, 18, 0, tzinfo=UTC)
    with sessions.begin() as session:
        job = session.get(ReviewJobModel, review_id)
        assert job is not None
        job.status = ReviewJobStatus.COMPLETED
        job.started_at = now
        job.completed_at = now
        job.updated_at = now
        job.process_pid = 4242
        job.model_name = "private-model"
        job.prompt_versions = {"secret": "private-prompt"}
        for ordinal in (1, 0):
            session.add(
                FindingModel(
                    company_id=settings.default_company_id,
                    review_job_id=review_id,
                    core_finding_id=f"core-{ordinal}",
                    ordinal=ordinal,
                    defect_id=f"DEFECT_{ordinal}",
                    severity="high" if ordinal == 0 else "low",
                    confidence=0.9 - ordinal * 0.1,
                    location={
                        "page": 1,
                        "section_path": ["Scope"],
                        "block_id": f"p-{ordinal}",
                    },
                    quote="Source text",
                    problem="Problem",
                    clarification="Possible correction",
                    detected_by=["private-analyzer"],
                    created_at=now,
                )
            )
    engine.dispose()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        status_response = await client.get(f"/api/reviews/{review_id}")
        findings_response = await client.get(f"/api/reviews/{review_id}/findings")
        unknown_id = uuid4()
        unknown = await client.get(f"/api/reviews/{unknown_id}")
        unknown_findings = await client.get(f"/api/reviews/{unknown_id}/findings")

    status_payload = status_response.json()
    assert status_payload["status"] == "completed"
    assert status_payload["stage"] == "result_ready"
    assert status_payload["poll_after_ms"] is None
    assert "Retry-After" not in status_response.headers
    serialized_status = status_response.text
    assert "private-model" not in serialized_status
    assert "private-prompt" not in serialized_status
    assert "4242" not in serialized_status

    findings = findings_response.json()
    assert findings["total"] == 2
    assert [item["ordinal"] for item in findings["items"]] == [0, 1]
    serialized_findings = findings_response.text
    assert "private-analyzer" not in serialized_findings
    assert "core-0" not in serialized_findings
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "REVIEW_NOT_FOUND"
    assert unknown_findings.status_code == 404
    assert unknown_findings.json()["error"]["code"] == "REVIEW_NOT_FOUND"
