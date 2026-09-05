import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from docreview_api.config import Settings
from docreview_api.db.base import Base
from docreview_api.db.models import CompanyModel, DocumentModel
from docreview_api.db.session import create_database_engine, create_session_factory
from docreview_api.maintenance import cleanup_uploads
from docreview_api.repositories.database import CompanyRepository, DocumentRepository
from docreview_api.services.orphaned_uploads import OrphanedUploadCleaner


def touch_at(path: Path, content: bytes, at: datetime) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    timestamp = at.timestamp()
    os.utime(path, (timestamp, timestamp))


def test_cleanup_removes_only_old_recognized_orphans_and_is_idempotent(tmp_path: Path, database_url: str) -> None:
    now = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
    old = now - timedelta(hours=25)
    recent = now - timedelta(hours=1)
    documents_dir = tmp_path / "documents"
    company_id = uuid4()
    referenced_id = uuid4()
    orphan_id = uuid4()
    recent_id = uuid4()
    company_directory = documents_dir / company_id.hex
    referenced = company_directory / f"{referenced_id.hex}.pdf"
    old_orphan = company_directory / f"{orphan_id.hex}.docx"
    recent_orphan = company_directory / f"{recent_id.hex}.pdf"
    old_temporary = documents_dir / ".incoming" / "upload-old.tmp"
    recent_temporary = documents_dir / ".incoming" / "upload-recent.tmp"
    unrelated = company_directory / "notes.txt"
    for path, moment in (
        (referenced, old),
        (old_orphan, old),
        (recent_orphan, recent),
        (old_temporary, old),
        (recent_temporary, recent),
        (unrelated, old),
    ):
        touch_at(path, b"test", moment)
    engine = create_database_engine(database_url)
    Base.metadata.create_all(engine)
    sessions = create_session_factory(engine)
    with sessions.begin() as session:
        CompanyRepository(session).add(
            CompanyModel(id=company_id, slug="cleanup", display_name="Cleanup")
        )
        DocumentRepository(session).add(
            DocumentModel(
                id=referenced_id,
                company_id=company_id,
                uploaded_by_user_id=None,
                original_filename="referenced.pdf",
                media_type="application/pdf",
                size_bytes=4,
                sha256="0" * 64,
                storage_key=f"{company_id.hex}/{referenced_id.hex}.pdf",
            )
        )

    cleaner = OrphanedUploadCleaner(documents_dir, sessions)
    report = cleaner.cleanup(now=now, grace_period=timedelta(hours=24))
    repeated = cleaner.cleanup(now=now, grace_period=timedelta(hours=24))

    assert report.scanned_files == 5
    assert report.deleted_temporary_files == 1
    assert report.deleted_unreferenced_files == 1
    assert report.failed_deletions == 0
    assert repeated.deleted_temporary_files == 0
    assert repeated.deleted_unreferenced_files == 0
    assert referenced.exists()
    assert recent_orphan.exists()
    assert recent_temporary.exists()
    assert unrelated.exists()
    assert not old_orphan.exists()
    assert not old_temporary.exists()
    engine.dispose()


def test_cleanup_requires_utc_and_positive_grace_period(tmp_path: Path, database_url: str) -> None:
    engine = create_database_engine(database_url)
    Base.metadata.create_all(engine)
    cleaner = OrphanedUploadCleaner(
        tmp_path / "documents",
        create_session_factory(engine),
    )

    with pytest.raises(ValueError, match="UTC"):
        cleaner.cleanup(
            now=datetime(2026, 9, 3, 12, 0),
            grace_period=timedelta(hours=24),
        )
    with pytest.raises(ValueError, match="positive"):
        cleaner.cleanup(
            now=datetime(2026, 9, 3, 12, 0, tzinfo=UTC),
            grace_period=timedelta(0),
        )
    engine.dispose()


def test_cleanup_cli_outputs_counts_without_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    database_url: str,
) -> None:
    engine = create_database_engine(database_url)
    Base.metadata.create_all(engine)
    engine.dispose()
    documents_dir = tmp_path / "documents"
    stale = documents_dir / ".incoming" / "upload-stale.tmp"
    touch_at(stale, b"private document content", datetime(2020, 1, 1, tzinfo=UTC))
    settings = Settings(
        environment="test",
        database_url=database_url,
        documents_dir=documents_dir,
        orphan_upload_grace_period_hours=24,
        _env_file=None,
    )
    monkeypatch.setattr(cleanup_uploads, "get_settings", lambda: settings)

    cleanup_uploads.main()

    output = capsys.readouterr().out
    assert json.loads(output) == {
        "deleted_temporary_files": 1,
        "deleted_unreferenced_files": 0,
        "failed_deletions": 0,
        "scanned_files": 1,
    }
    assert "private document content" not in output
    assert str(documents_dir) not in output
