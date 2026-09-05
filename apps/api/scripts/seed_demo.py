"""Idempotently seed the single-company demo profile when explicitly enabled."""

from __future__ import annotations

import os
import sys
from uuid import UUID

from sqlalchemy import select

from docreview_api.config import get_settings
from docreview_api.db import create_database_engine, create_session_factory
from docreview_api.db.models import CompanyModel, ReviewPackReferenceModel
from docreview_api.services.review_packs import load_review_pack_manifest

DEMO_PACK_ID = UUID("00000000-0000-0000-0000-000000000002")


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

    pack_locator = os.environ.get("DOCREVIEW_DEMO_PACK_LOCATOR", "").strip()
    manifest = load_review_pack_manifest(settings.review_packs_dir, pack_locator)
    if manifest is None:
        print(
            "Demo Review Pack manifest is missing or invalid; "
            "set DOCREVIEW_DEMO_PACK_LOCATOR to a server-approved relative directory.",
            file=sys.stderr,
        )
        return 3

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

        pack = session.scalar(
            select(ReviewPackReferenceModel).where(
                ReviewPackReferenceModel.company_id == company.id,
                ReviewPackReferenceModel.pack_key == manifest.pack_key,
                ReviewPackReferenceModel.version == manifest.version,
            )
        )
        if pack is None:
            session.add(
                ReviewPackReferenceModel(
                    id=DEMO_PACK_ID,
                    company_id=company.id,
                    pack_key=manifest.pack_key,
                    version=manifest.version,
                    display_name=manifest.display_name,
                    document_type=manifest.document_type,
                    locator=pack_locator,
                    checksum=None,
                )
            )
        else:
            pack.display_name = manifest.display_name
            pack.document_type = manifest.document_type
            pack.locator = pack_locator
    return 0


if __name__ == "__main__":
    sys.exit(main())
