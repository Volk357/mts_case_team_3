import json
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
                raw_result={"immutable": suffix, "api_token": "do-not-export"},
                schema_version="1.0.0",
                engine_version="mock-2.1",
                result_review_pack_id=f"pack-{suffix}",
                result_review_pack_version="1.0",
                model_name="qwen-test",
                prompt_versions={"reviewer": "reviewer-3"},
                diagnostic_message="private diagnostic",
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
        assert finding.review_job.raw_result == {
            "immutable": "own",
            "api_token": "do-not-export",
        }
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
async def test_feedback_rejects_finding_with_cross_tenant_review_parent(
    feedback_resources: tuple[Settings, UUID, UUID],
) -> None:
    settings, finding_id, foreign_finding_id = feedback_resources
    engine = create_database_engine(settings.database_url)
    sessions = create_session_factory(engine)
    with sessions.begin() as session:
        finding = session.get(FindingModel, finding_id)
        foreign_finding = session.get(FindingModel, foreign_finding_id)
        assert finding is not None
        assert foreign_finding is not None
        review = session.get(ReviewJobModel, finding.review_job_id)
        assert review is not None
        review.company_id = foreign_finding.company_id
    engine.dispose()

    app = create_app(settings)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.put(
            f"/api/findings/{finding_id}/feedback",
            json={"decision": "accepted"},
            headers={"X-Actor-Key": "browser-session-1"},
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "FINDING_NOT_FOUND"


@pytest.mark.anyio
async def test_feedback_export_is_version_linked_filterable_and_data_minimized(
    feedback_resources: tuple[Settings, UUID, UUID],
) -> None:
    settings, finding_id, foreign_finding_id = feedback_resources
    engine = create_database_engine(settings.database_url)
    sessions = create_session_factory(engine)
    with sessions.begin() as session:
        finding = session.get(FindingModel, finding_id)
        foreign_finding = session.get(FindingModel, foreign_finding_id)
        assert finding is not None
        assert foreign_finding is not None
        review = session.get(ReviewJobModel, finding.review_job_id)
        assert review is not None
        pack_id = review.review_pack_reference_id
        session.add(
            FindingFeedbackModel(
                company_id=foreign_finding.company_id,
                finding_id=foreign_finding.id,
                actor_key="foreign-private-actor",
                decision="accepted",
                comment="Must stay outside the tenant export",
            )
        )
    engine.dispose()

    app = create_app(settings)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        saved = await client.put(
            f"/api/findings/{finding_id}/feedback",
            json={"decision": "false_positive", "comment": "Checked manually"},
            headers={"X-Actor-Key": "sensitive-browser-session"},
        )
        exported = await client.get("/api/feedback/export")
        matching_pack = await client.get(
            "/api/feedback/export",
            params={"review_pack_id": str(pack_id)},
        )
        another_pack = await client.get(
            "/api/feedback/export",
            params={"review_pack_id": str(uuid4())},
        )
        future = await client.get(
            "/api/feedback/export",
            params={"updated_from": "2100-01-01T00:00:00Z"},
        )
        invalid_range = await client.get(
            "/api/feedback/export",
            params={
                "updated_from": "2026-09-05T00:00:00Z",
                "updated_to": "2026-09-04T00:00:00Z",
            },
        )

    assert saved.status_code == 200
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("application/x-ndjson")
    assert exported.headers["content-disposition"] == 'attachment; filename="feedback-export.jsonl"'
    records = [json.loads(line) for line in exported.text.splitlines()]
    assert len(records) == 1
    record = records[0]
    assert record["run_id"] == "review-own"
    assert record["finding_id"] == str(finding_id)
    assert record["core_finding_id"] == "core-own"
    assert record["review_pack_reference_id"] == str(pack_id)
    assert record["review_pack_key"] == "pack-own"
    assert record["review_pack_version"] == "1.0"
    assert record["result_review_pack_id"] == "pack-own"
    assert record["result_review_pack_version"] == "1.0"
    assert record["schema_version"] == "1.0.0"
    assert record["engine_version"] == "mock-2.1"
    assert record["model_name"] == "qwen-test"
    assert record["prompt_versions"] == {"reviewer": "reviewer-3"}
    assert record["decision"] == "false_positive"
    assert record["comment"] == "Checked manually"
    assert "actor_key" not in record
    assert "submitted_by_user_id" not in record
    assert "raw_result" not in record
    assert "diagnostic_message" not in record
    assert "sensitive-browser-session" not in exported.text
    assert "do-not-export" not in exported.text
    assert len(matching_pack.text.splitlines()) == 1
    assert another_pack.text == ""
    assert future.text == ""
    assert invalid_range.status_code == 422
    assert invalid_range.json()["error"]["code"] == "FEEDBACK_EXPORT_FILTER_INVALID"


@pytest.mark.anyio
async def test_feedback_metrics_cover_funnel_defects_timing_and_scope_filters(
    feedback_resources: tuple[Settings, UUID, UUID],
) -> None:
    settings, finding_id, foreign_finding_id = feedback_resources
    created_at = datetime(2026, 9, 4, 6, 0, tzinfo=UTC)
    engine = create_database_engine(settings.database_url)
    sessions = create_session_factory(engine)
    with sessions.begin() as session:
        finding = session.get(FindingModel, finding_id)
        foreign_finding = session.get(FindingModel, foreign_finding_id)
        assert finding is not None
        assert foreign_finding is not None
        review = session.get(ReviewJobModel, finding.review_job_id)
        assert review is not None
        pack_id = review.review_pack_reference_id
        false_positive_finding = FindingModel(
            company_id=finding.company_id,
            review_job_id=finding.review_job_id,
            core_finding_id="core-own-2",
            ordinal=1,
            defect_id="AMBIGUOUS_LOGIC",
            severity="medium",
            confidence=0.8,
            location={"page": 2, "section_path": ["Logic"], "block_id": "b-2"},
            quote="Another quote",
            problem="Another problem",
            clarification="Another clarification",
            detected_by=["reviewer"],
            created_at=created_at,
        )
        unevaluated_finding = FindingModel(
            company_id=finding.company_id,
            review_job_id=finding.review_job_id,
            core_finding_id="core-own-3",
            ordinal=2,
            defect_id="MISSING_LOGS",
            severity="low",
            confidence=0.7,
            location={"page": 3, "section_path": ["Logs"], "block_id": "b-3"},
            quote="Logs quote",
            problem="Logs problem",
            clarification="Logs clarification",
            detected_by=["reviewer"],
            created_at=created_at,
        )
        session.add_all([false_positive_finding, unevaluated_finding])
        session.flush()
        session.add_all(
            [
                FindingFeedbackModel(
                    company_id=finding.company_id,
                    finding_id=finding.id,
                    actor_key="metrics-actor",
                    decision="accepted",
                    comment=None,
                    created_at=created_at.replace(minute=10),
                    updated_at=created_at.replace(minute=10),
                ),
                FindingFeedbackModel(
                    company_id=false_positive_finding.company_id,
                    finding_id=false_positive_finding.id,
                    actor_key="metrics-actor",
                    decision="false_positive",
                    comment=None,
                    created_at=created_at.replace(minute=20),
                    updated_at=created_at.replace(minute=20),
                ),
                FindingFeedbackModel(
                    company_id=foreign_finding.company_id,
                    finding_id=foreign_finding.id,
                    actor_key="foreign-metrics-actor",
                    decision="accepted",
                    comment=None,
                    created_at=created_at.replace(minute=5),
                    updated_at=created_at.replace(minute=5),
                ),
            ]
        )
    engine.dispose()

    app = create_app(settings)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/feedback/metrics")
        matching_pack = await client.get(
            "/api/feedback/metrics",
            params={"review_pack_id": str(pack_id)},
        )
        empty_pack = await client.get(
            "/api/feedback/metrics",
            params={"review_pack_id": str(uuid4())},
        )
        future = await client.get(
            "/api/feedback/metrics",
            params={"finding_created_from": "2100-01-01T00:00:00Z"},
        )
        invalid_range = await client.get(
            "/api/feedback/metrics",
            params={
                "finding_created_from": "2026-09-05T00:00:00Z",
                "finding_created_to": "2026-09-04T00:00:00Z",
            },
        )

    assert response.status_code == 200
    metrics = response.json()
    assert metrics["total_findings"] == 3
    assert metrics["evaluated_findings"] == 2
    assert metrics["unevaluated_findings"] == 1
    assert metrics["unevaluated_share"] == 0.3333
    assert metrics["total_decisions"] == 2
    assert metrics["accepted_decisions"] == 1
    assert metrics["accepted_share"] == 0.5
    assert metrics["average_time_to_first_decision_seconds"] == 900.0
    assert metrics["false_positive_by_defect"] == [
        {
            "defect_id": "AMBIGUOUS_LOGIC",
            "evaluated_decisions": 2,
            "false_positive_decisions": 1,
            "false_positive_rate": 0.5,
        },
        {
            "defect_id": "MISSING_LOGS",
            "evaluated_decisions": 0,
            "false_positive_decisions": 0,
            "false_positive_rate": None,
        },
    ]
    assert "Recall@20" in metrics["quality_scope"]
    assert matching_pack.json() == metrics
    empty_metrics = empty_pack.json()
    assert empty_metrics["total_findings"] == 0
    assert empty_metrics["accepted_share"] is None
    assert empty_metrics["unevaluated_share"] is None
    assert empty_metrics["average_time_to_first_decision_seconds"] is None
    assert empty_metrics["false_positive_by_defect"] == []
    assert future.json()["total_findings"] == 0
    assert invalid_range.status_code == 422
    assert invalid_range.json()["error"]["code"] == "FEEDBACK_METRICS_FILTER_INVALID"


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
    export_operation = schema["paths"]["/api/feedback/export"]["get"]
    assert "application/x-ndjson" in export_operation["responses"]["200"]["content"]
    metrics_operation = schema["paths"]["/api/feedback/metrics"]["get"]
    assert metrics_operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/FeedbackMetricsResponse"
    }
