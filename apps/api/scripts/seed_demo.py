"""Idempotently seed the single-company demo profile when explicitly enabled."""

from __future__ import annotations

import os
import sys
from uuid import UUID, uuid5

from sqlalchemy import select

from docreview_api.config import get_settings
from docreview_api.db import create_database_engine, create_session_factory
from docreview_api.db.models import CompanyModel, ReviewPackReferenceModel
from docreview_api.services.review_packs import discover_review_pack_manifests

DEMO_PACK_ID = UUID("00000000-0000-0000-0000-000000000002")
DEMO_PACK_NAMESPACE = UUID("fdde89c0-d197-462b-925a-260839202682")


def main() -> int:
    settings = get_settings()
    explicitly_enabled = os.environ.get("DOCREVIEW_ALLOW_DEMO_SEED", "").casefold() == "true"
    if settings.environment != "demo" or not explicitly_enabled:
        print(
            "Demo seed is disabled; require DOCREVIEW_ENVIRONMENT=demo and "
            "DOCREVIEW_ALLOW_DEMO_SEED=true.",
            file=sys.stderr,
        )
        return 2

    discovered = discover_review_pack_manifests(settings.review_packs_dir)
    if not discovered:
        print(
            "No valid Review Pack manifests were found in the configured catalog.",
            file=sys.stderr,
        )
        return 3
    preferred_locator = os.environ.get("DOCREVIEW_DEMO_PACK_LOCATOR", "").strip()
    if preferred_locator and all(item.locator != preferred_locator for item in discovered):
        print(
            "DOCREVIEW_DEMO_PACK_LOCATOR does not identify a valid discovered Review Pack.",
            file=sys.stderr,
        )
        return 3
    primary_locator = preferred_locator or discovered[0].locator

    sessions = create_session_factory(create_database_engine(settings.database_url))
    with sessions.begin() as session:
        company = session.get(CompanyModel, settings.default_company_id)
        if company is None:
            company = CompanyModel(
                id=settings.default_company_id,
                slug=settings.default_company_slug,
                display_name=settings.default_company_name,
            )
            session.add(company)
            session.flush()

        existing = {
            (record.pack_key, record.version): record
            for record in session.scalars(
                select(ReviewPackReferenceModel).where(
                    ReviewPackReferenceModel.company_id == company.id,
                )
            ).all()
        }
        primary_id_available = session.get(ReviewPackReferenceModel, DEMO_PACK_ID) is None
        for item in discovered:
            manifest = item.manifest
            key = (manifest.pack_key, manifest.version)
            pack = existing.get(key)
            if pack is None:
                generated_id = uuid5(
                    DEMO_PACK_NAMESPACE,
                    f"{company.id}:{manifest.pack_key}:{manifest.version}",
                )
                pack = ReviewPackReferenceModel(
                    id=(
                        DEMO_PACK_ID
                        if item.locator == primary_locator and primary_id_available
                        else generated_id
                    ),
                    company_id=company.id,
                    pack_key=manifest.pack_key,
                    version=manifest.version,
                    display_name=manifest.display_name,
                    document_type=manifest.document_type,
                    locator=item.locator,
                    checksum=None,
                )
                session.add(pack)
                existing[key] = pack
                if pack.id == DEMO_PACK_ID:
                    primary_id_available = False
            else:
                pack.display_name = manifest.display_name
                pack.document_type = manifest.document_type
                pack.locator = item.locator
    return 0


if __name__ == "__main__":
    sys.exit(main())
