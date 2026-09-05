"""Idempotently seed the single-company demo profile when explicitly enabled."""

from __future__ import annotations

import os
import sys
from uuid import UUID

from sqlalchemy import select

from docreview_api.config import get_settings
from docreview_api.db import create_database_engine, create_session_factory
from docreview_api.db.models import CompanyModel, ReviewPackReferenceModel

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
                ReviewPackReferenceModel.pack_key == "mts-net",
                ReviewPackReferenceModel.version == "0.2",
            )
        )
        if pack is None:
            session.add(
                ReviewPackReferenceModel(
                    id=DEMO_PACK_ID,
                    company_id=company.id,
                    pack_key="mts-net",
                    version="0.2",
                    display_name="Потоковые данные и витрины",
                    document_type="data_mart_or_stream",
                    locator="mts-net/0.2",
                    checksum=None,
                )
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
