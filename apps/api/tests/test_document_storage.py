from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import Session, sessionmaker

from docreview_api.db.base import Base
from docreview_api.db.models import DocumentModel
from docreview_api.db.session import create_database_engine, create_session_factory
from docreview_api.services.antivirus import (
    AntivirusRejectedError,
    AntivirusScanner,
    AntivirusScanRequest,
    disabled_antivirus_scanner,
)
from docreview_api.services.document_storage import (
    STORED_FILE_MODE,
    TEMPORARY_FILE_MODE,
    DocumentStorageService,
    UnsafeStorageKeyError,
)
from docreview_api.services.upload_metrics import UploadMetrics
from docreview_api.services.upload_validation import PDF_MEDIA_TYPE


def storage_service(
    documents_dir: Path,
    sessions: sessionmaker[Session],
    *,
    scanner: AntivirusScanner = disabled_antivirus_scanner,
    metrics: UploadMetrics | None = None,
) -> DocumentStorageService:
    return DocumentStorageService(
        documents_dir,
        sessions,
        antivirus_scanner=scanner,
        metrics=metrics or UploadMetrics(),
    )


class BrokenUpload:
    filename = "interrupted.pdf"
    content_type = PDF_MEDIA_TYPE

    def __init__(self) -> None:
        self.calls = 0

    async def read(self, size: int = -1) -> bytes:
        self.calls += 1
        if self.calls == 1:
            return b"%PDF-1.7\n"
        raise ConnectionError("client disconnected")


class ValidPdfUpload:
    filename = "valid.pdf"
    content_type = PDF_MEDIA_TYPE

    def __init__(self) -> None:
        self.content = b"%PDF-1.7\n%%EOF"

    async def read(self, size: int = -1) -> bytes:
        content, self.content = self.content, b""
        return content


@pytest.mark.anyio
async def test_interrupted_upload_leaves_no_file_or_document(tmp_path: Path, database_url: str) -> None:
    engine = create_database_engine(database_url)
    Base.metadata.create_all(engine)
    sessions = create_session_factory(engine)
    documents_dir = tmp_path / "documents"
    service = storage_service(documents_dir, sessions)

    with pytest.raises(ConnectionError, match="disconnected"):
        await service.store(
            BrokenUpload(),
            max_size_bytes=1024,
            company_id=uuid4(),
            company_slug="test",
            company_name="Test",
        )

    assert not [path for path in documents_dir.rglob("*") if path.is_file()]
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(DocumentModel)) == 0
    engine.dispose()


def test_storage_key_resolution_stays_inside_configured_root(tmp_path: Path, database_url: str) -> None:
    engine = create_database_engine(database_url)
    service = storage_service(tmp_path / "documents", create_session_factory(engine))

    resolved = service.absolute_path("tenant/document.pdf")

    assert resolved == (tmp_path / "documents" / "tenant" / "document.pdf").resolve()
    with pytest.raises(UnsafeStorageKeyError):
        service.absolute_path("../outside/document.pdf")
    with pytest.raises(UnsafeStorageKeyError):
        service.absolute_path("tenant\\document.pdf")
    with pytest.raises(UnsafeStorageKeyError):
        service.absolute_path("C:/outside/document.pdf")
    with pytest.raises(UnsafeStorageKeyError):
        service.absolute_path("")
    engine.dispose()


@pytest.mark.anyio
async def test_database_failure_removes_already_moved_file(tmp_path: Path, database_url: str) -> None:
    engine = create_database_engine(database_url)
    sessions = create_session_factory(engine)
    documents_dir = tmp_path / "documents"
    service = storage_service(documents_dir, sessions)

    with pytest.raises(DatabaseError, match="companies"):
        await service.store(
            ValidPdfUpload(),
            max_size_bytes=1024,
            company_id=uuid4(),
            company_slug="test",
            company_name="Test",
        )

    assert not [path for path in documents_dir.rglob("*") if path.is_file()]
    engine.dispose()


@pytest.mark.anyio
async def test_antivirus_rejection_cleans_upload_and_records_failure(tmp_path: Path, database_url: str) -> None:
    engine = create_database_engine(database_url)
    Base.metadata.create_all(engine)
    sessions = create_session_factory(engine)
    metrics = UploadMetrics()

    class RejectingScanner:
        async def scan(self, request: AntivirusScanRequest) -> None:
            assert request.path.read_bytes() == b"%PDF-1.7\n%%EOF"
            assert request.sha256
            raise AntivirusRejectedError("Document rejected by antivirus")

    documents_dir = tmp_path / "documents"
    service = storage_service(
        documents_dir,
        sessions,
        scanner=RejectingScanner(),
        metrics=metrics,
    )
    with pytest.raises(AntivirusRejectedError):
        await service.store(
            ValidPdfUpload(),
            max_size_bytes=1024,
            company_id=uuid4(),
            company_slug="test",
            company_name="Test",
        )

    assert not [path for path in documents_dir.rglob("*") if path.is_file()]
    assert metrics.snapshot().failures_by_reason == {"AntivirusRejectedError": 1}
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(DocumentModel)) == 0
    engine.dispose()


@pytest.mark.anyio
async def test_success_records_size_and_applies_file_permissions(tmp_path: Path, database_url: str) -> None:
    engine = create_database_engine(database_url)
    Base.metadata.create_all(engine)
    sessions = create_session_factory(engine)
    metrics = UploadMetrics()
    service = storage_service(tmp_path / "documents", sessions, metrics=metrics)

    with patch("docreview_api.services.document_storage.os.chmod") as chmod:
        stored = await service.store(
            ValidPdfUpload(),
            max_size_bytes=1024,
            company_id=uuid4(),
            company_slug="test",
            company_name="Test",
        )

    applied_modes = [call.args[1] for call in chmod.call_args_list]
    assert TEMPORARY_FILE_MODE in applied_modes
    assert STORED_FILE_MODE in applied_modes
    assert metrics.snapshot().successful_uploads == 1
    assert metrics.snapshot().uploaded_bytes == stored.size_bytes
    engine.dispose()
