"""CLI entry point for explicit orphaned-upload cleanup."""

import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta

from docreview_api.config import get_settings
from docreview_api.db.session import create_database_engine, create_session_factory
from docreview_api.services.orphaned_uploads import OrphanedUploadCleaner


def main() -> None:
    settings = get_settings()
    engine = create_database_engine(settings.database_url)
    try:
        report = OrphanedUploadCleaner(
            settings.documents_dir,
            create_session_factory(engine),
        ).cleanup(
            now=datetime.now(UTC),
            grace_period=timedelta(hours=settings.orphan_upload_grace_period_hours),
        )
    finally:
        engine.dispose()
    print(json.dumps(asdict(report), sort_keys=True))


if __name__ == "__main__":
    main()
