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
    FindingFeedbackModel,
    FindingModel,
    ReviewJobModel,
    ReviewPackReferenceModel,
)
from docreview_api.db.session import create_database_engine, create_session_factory
from docreview_api.main import create_app


@pytest.fixture
def feedback_resources(tmp_path: Path) -> tuple[Settings, UUID, UUID]:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'feedback.db').as_posix()}",
        _env_file=None,
    )
    engine = create_database_engine(settings.database_url)
    Base.metadata.create_all(engine)
    sessions = create_session_factory(engine)
    now = datetime(2026, 9, 4, 6, 0, tzinfo=UTC)
    with sessions.begin() as session:
        company = CompanyModel(
            id=settings.default_company_id,
            slug=settings.default_company_slug,
            display_name=settings.default_company_name,
        )
        foreign_company = CompanyModel(slug="foreign-feedback", display_name="Foreign")
        session.add_all([company, foreign_company])
        session.flush()

        finding_ids: list[UUID] = []
        for owner, suffix in ((company, "own"), (foreign_company, "foreign")):
            document = DocumentModel(
                company_id=owner.id,
                original_filename=f"{suffix}.pdf",
                media_type="application/pdf",
                size_bytes=10,
                sha256=("a" if suffix == "own" else "b") * 64,
                storage_key=f"{suffix}/document.pdf",
            )
            pack = ReviewPackReferenceModel(
                company_id=owner.id,
                pack_key=f"pack-{suffix}",
                version="1.0",
                display_name=f"Pack {suffix}",
                document_type="technical_specification",
                locator=f"packs/{suffix}",
            )
            session.add_all([document, pack])
            session.flush()
            job = ReviewJobModel(
                run_id=f"review-{suffix}",
                company_id=owner.id,
                document_id=document.id,
                review_pack_reference_id=pack.id,
                raw_result={"immutable": suffix},
                queued_at=now,
                created_at=now,
                updated_at=now,
            )
            session.add(job)
            session.flush()
            finding = FindingModel(
                company_id=owner.id,
                review_job_id=job.id,
                core_finding_id=f"core-{suffix}",
                ordinal=0,
                defect_id="AMBIGUOUS_LOGIC",
                severity="high",
                confidence=0.91,
                location={"page": 1, "section_path": ["Logic"], "block_id": "b-1"},
                quote="Original quote",
                problem="Original problem",
                clarification="Original clarification",
                detected_by=["reviewer"],
                created_at=now,
            )
            session.add(finding)
            session.flush()
            finding_ids.append(finding.id)
    engine.dispose()
    return settings, finding_ids[0], finding_ids[1]


@pytest.mark.anyio
async def test_feedback_upsert_changes_decision_without_mutating_finding(
    feedback_resources: tuple[Settings, UUID, UUID],
) -> None:
    settings, finding_id, _ = feedback_resources
    app = create_app(settings)
    headers = {"X-Actor-Key": " browser-session-1 "}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.put(
            f"/api/findings/{finding_id}/feedback",
            json={"decision": "accepted", "comment": " Useful finding "},
            headers=headers,
        )
        updated = await client.put(
            f"/api/findings/{finding_id}/feedback",
            json={"decision": "false_positive", "comment": "   "},
            headers=headers,
        )

    assert created.status_code == 200
    assert updated.status_code == 200
    assert created.json()["feedback_id"] == updated.json()["feedback_id"]
    assert created.json()["comment"] == "Useful finding"
    assert updated.json()["decision"] == "false_positive"
    assert updated.json()["comment"] is None
    assert updated.json()["created_at"].endswith("Z")
    assert updated.json()["updated_at"].endswith("Z")

    engine = create_database_engine(settings.database_url)
    sessions = create_session_factory(engine)
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(FindingFeedbackModel)) == 1
        finding = session.get(FindingModel, finding_id)
        assert finding is not None
        assert finding.quote == "Original quote"
        assert finding.problem == "Original problem"
        assert finding.review_job.raw_result == {"immutable": "own"}
    engine.dispose()


@pytest.mark.anyio
async def test_feedback_list_restores_only_the_current_actor_decisions(
    feedback_resources: tuple[Settings, UUID, UUID],
) -> None:
    settings, finding_id, _ = feedback_resources
    app = create_app(settings)
    engine = create_database_engine(settings.database_url)
    sessions = create_session_factory(engine)
    with sessions() as session:
        finding = session.get(FindingModel, finding_id)
        assert finding is not None
        review_id = finding.review_job_id
    engine.dispose()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        saved = await client.put(
            f"/api/findings/{finding_id}/feedback",
            json={"decision": "already_described", "comment": "See section 4"},
            headers={"X-Actor-Key": "browser-session-1"},
        )
        restored = await client.get(
            f"/api/reviews/{review_id}/feedback",
            headers={"X-Actor-Key": "browser-session-1"},
        )
        another_actor = await client.get(
            f"/api/reviews/{review_id}/feedback",
            headers={"X-Actor-Key": "browser-session-2"},
        )
        missing_review = await client.get(
            f"/api/reviews/{uuid4()}/feedback",
            headers={"X-Actor-Key": "browser-session-1"},
        )

    assert saved.status_code == 200
    assert restored.status_code == 200
    assert restored.json()["total"] == 1
    assert restored.json()["items"][0] == saved.json()
    assert another_actor.json()["items"] == []
    assert missing_review.status_code == 404
    assert missing_review.json()["error"]["code"] == "REVIEW_NOT_FOUND"


@pytest.mark.anyio
async def test_feedback_validates_decision_actor_and_tenant_boundary(
    feedback_resources: tuple[Settings, UUID, UUID],
) -> None:
    settings, finding_id, foreign_finding_id = feedback_resources
    app = create_app(settings)
    valid_headers = {"X-Actor-Key": "browser-session-1"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        invalid_decision = await client.put(
            f"/api/findings/{finding_id}/feedback",
            json={"decision": "maybe"},
            headers=valid_headers,
        )
        missing_actor = await client.put(
            f"/api/findings/{finding_id}/feedback",
            json={"decision": "accepted"},
        )
        foreign = await client.put(
            f"/api/findings/{foreign_finding_id}/feedback",
            json={"decision": "accepted"},
            headers=valid_headers,
        )
        missing = await client.put(
            f"/api/findings/{uuid4()}/feedback",
            json={"decision": "accepted"},
            headers=valid_headers,
        )

    assert invalid_decision.status_code == 422
    assert invalid_decision.json()["error"]["code"] == "REQUEST_VALIDATION_ERROR"
    assert missing_actor.status_code == 422
    assert foreign.status_code == 404
    assert missing.status_code == 404
    assert (
        foreign.json()
        == missing.json()
        == {
            "error": {
                "code": "FINDING_NOT_FOUND",
                "message": "Finding was not found.",
                "details": [],
            }
        }
    )


@pytest.mark.anyio
async def test_feedback_contract_is_published_in_openapi(
    feedback_resources: tuple[Settings, UUID, UUID],
) -> None:
    settings, _, _ = feedback_resources
    app = create_app(settings)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        schema = (await client.get("/api/openapi.json")).json()

    operation = schema["paths"]["/api/findings/{finding_id}/feedback"]["put"]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/FeedbackResponse"
    }
    decision_schema = schema["components"]["schemas"]["FeedbackDecision"]
    assert set(decision_schema["enum"]) == {
        "accepted",
        "false_positive",
        "allowed_exception",
        "already_described",
        "not_relevant",
    }
    list_operation = schema["paths"]["/api/reviews/{review_id}/feedback"]["get"]
    assert list_operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/FeedbackListResponse"
    }
