from pathlib import Path
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient

from docreview_api.config import Settings
from docreview_api.db.base import Base
from docreview_api.db.models import CompanyModel, ReviewPackReferenceModel
from docreview_api.db.session import create_database_engine, create_session_factory
from docreview_api.main import create_app
from docreview_api.services.review_packs import discover_review_pack_manifests


@pytest.fixture
def catalog_settings(tmp_path: Path, database_url: str) -> tuple[Settings, UUID, UUID]:
    packs_root = tmp_path / "review-packs"
    (packs_root / "requirements-v1").mkdir(parents=True)
    (packs_root / "requirements-v1" / "pack.yaml").write_text(
        """id: requirements
version: '1.0'
name: Architecture requirements
document_type: architecture_decision
description: Rules supplied by the Review Pack manifest.
""",
        encoding="utf-8",
    )
    (packs_root / "inactive").mkdir()
    (packs_root / "inactive" / "pack.yaml").write_text(
        """id: inactive
version: '1.0'
name: Inactive
document_type: technical_specification
description: Inactive pack.
""",
        encoding="utf-8",
    )
    (packs_root / "foreign").mkdir()
    (packs_root / "foreign" / "pack.yaml").write_text(
        """id: foreign
version: '1.0'
name: Foreign
document_type: technical_specification
description: Another tenant pack.
""",
        encoding="utf-8",
    )
    (packs_root / "mismatched").mkdir()
    (packs_root / "mismatched" / "pack.yaml").write_text(
        """id: another-pack
version: '1.0'
name: Mismatched
document_type: technical_specification
description: The manifest id does not match the allowlist record.
""",
        encoding="utf-8",
    )
    (packs_root / "empty").mkdir()

    settings = Settings(
        environment="test",
        database_url=database_url,
        review_packs_dir=packs_root,
        _env_file=None,
    )
    engine = create_database_engine(settings.database_url)
    Base.metadata.create_all(engine)
    sessions = create_session_factory(engine)
    with sessions.begin() as session:
        company = CompanyModel(
            id=settings.default_company_id,
            slug=settings.default_company_slug,
            display_name="Example Company",
        )
        foreign_company = CompanyModel(slug="foreign", display_name="Foreign")
        session.add_all([company, foreign_company])
        session.flush()
        visible = ReviewPackReferenceModel(
            company_id=company.id,
            pack_key="requirements",
            version="1.0",
            display_name="Requirements",
            document_type="technical_specification",
            locator="requirements-v1",
        )
        session.add_all(
            [
                visible,
                ReviewPackReferenceModel(
                    company_id=company.id,
                    pack_key="inactive",
                    version="1.0",
                    display_name="Inactive",
                    document_type="technical_specification",
                    locator="inactive",
                    is_active=False,
                ),
                ReviewPackReferenceModel(
                    company_id=company.id,
                    pack_key="mismatched",
                    version="1.0",
                    display_name="Must stay hidden",
                    document_type="technical_specification",
                    locator="mismatched",
                ),
                ReviewPackReferenceModel(
                    company_id=company.id,
                    pack_key="missing",
                    version="1.0",
                    display_name="Missing",
                    document_type="technical_specification",
                    locator="missing",
                ),
                ReviewPackReferenceModel(
                    company_id=company.id,
                    pack_key="unsafe",
                    version="1.0",
                    display_name="Unsafe",
                    document_type="technical_specification",
                    locator="../outside",
                ),
                ReviewPackReferenceModel(
                    company_id=company.id,
                    pack_key="empty",
                    version="1.0",
                    display_name="Empty directory",
                    document_type="technical_specification",
                    locator="empty",
                ),
                ReviewPackReferenceModel(
                    company_id=foreign_company.id,
                    pack_key="foreign",
                    version="1.0",
                    display_name="Foreign",
                    document_type="technical_specification",
                    locator="foreign",
                ),
            ]
        )
        session.flush()
        visible_id = visible.id
        foreign_id = foreign_company.id
    engine.dispose()
    return settings, visible_id, foreign_id


@pytest.mark.anyio
async def test_catalog_returns_only_active_valid_tenant_packs_without_locator(
    catalog_settings: tuple[Settings, UUID, UUID],
) -> None:
    settings, visible_id, _ = catalog_settings
    app = create_app(settings)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/review-packs")

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "review_pack_id": str(visible_id),
                "company_name": "Example Company",
                "display_name": "Architecture requirements",
                "document_type": "architecture_decision",
                "version": "1.0",
                "description": "Rules supplied by the Review Pack manifest.",
            }
        ],
        "total": 1,
    }
    assert "locator" not in response.text
    assert "checksum" not in response.text
    assert str(settings.review_packs_dir) not in response.text


@pytest.mark.anyio
async def test_catalog_is_declared_in_openapi(
    catalog_settings: tuple[Settings, UUID, UUID],
) -> None:
    settings, _, _ = catalog_settings
    app = create_app(settings)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        schema = (await client.get("/api/openapi.json")).json()

    operation = schema["paths"]["/api/review-packs"]["get"]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ReviewPackListResponse"
    }
    public_fields = schema["components"]["schemas"]["ReviewPackResponse"]["properties"]
    assert set(public_fields) == {
        "review_pack_id",
        "company_name",
        "display_name",
        "document_type",
        "version",
        "description",
    }
    assert operation.get("parameters", []) == []


def test_discovery_scans_only_valid_id_and_version_directories(tmp_path: Path) -> None:
    root = tmp_path / "review-packs"
    valid = root / "architecture" / "2.0"
    valid.mkdir(parents=True)
    (valid / "pack.yaml").write_text(
        """id: architecture
version: '2.0'
name: Architecture
document_type: decision_record
description: Architecture decision rules.
""",
        encoding="utf-8",
    )
    invalid = root / "security" / "1.0"
    invalid.mkdir(parents=True)
    (invalid / "pack.yaml").write_text(
        """id: another-id
version: '1.0'
name: Security
document_type: specification
description: Mismatched directory id.
""",
        encoding="utf-8",
    )

    discovered = discover_review_pack_manifests(root)

    assert [(item.locator, item.manifest.pack_key) for item in discovered] == [
        ("architecture/2.0", "architecture")
    ]
