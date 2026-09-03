"""Atomic filesystem storage and persistence for validated document uploads."""

from __future__ import annotations

import hashlib
import os
from contextlib import suppress
from pathlib import Path, PurePosixPath, PureWindowsPath
from tempfile import mkstemp
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy.orm import Session, sessionmaker

from docreview_api.db.models import CompanyModel, DocumentModel
from docreview_api.repositories.database import CompanyRepository, DocumentRepository
from docreview_api.services.antivirus import AntivirusScanner, AntivirusScanRequest
from docreview_api.services.upload_metrics import UploadMetrics
from docreview_api.services.upload_validation import (
    EmptyDocumentError,
    UploadTooLargeError,
    validate_stored_format,
    validate_upload_metadata,
)

READ_CHUNK_SIZE = 1024 * 1024
DIRECTORY_MODE = 0o750
TEMPORARY_FILE_MODE = 0o600
STORED_FILE_MODE = 0o640


class AsyncUpload(Protocol):
    """Minimal upload stream required by storage, independent of FastAPI."""

    filename: str | None
    content_type: str | None

    async def read(self, size: int = -1) -> bytes: ...


class UnsafeStorageKeyError(ValueError):
    """Raised when a persisted storage key could escape the configured root."""


class DocumentStorageService:
    """Store files atomically and create Document only after the move succeeds."""

    def __init__(
        self,
        documents_dir: Path,
        session_factory: sessionmaker[Session],
        *,
        antivirus_scanner: AntivirusScanner,
        metrics: UploadMetrics,
    ) -> None:
        self.documents_dir = documents_dir.resolve()
        self.session_factory = session_factory
        self.antivirus_scanner = antivirus_scanner
        self.metrics = metrics

    @staticmethod
    def _ensure_directory(path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        os.chmod(path, DIRECTORY_MODE)

    def absolute_path(self, storage_key: str) -> Path:
        """Resolve an internal storage key for Job Runner without exposing it over HTTP."""

        key = PurePosixPath(storage_key)
        if (
            not storage_key
            or key.is_absolute()
            or PureWindowsPath(storage_key).is_absolute()
            or ".." in key.parts
            or "\\" in storage_key
        ):
            raise UnsafeStorageKeyError("storage key must be a safe relative POSIX path")
        resolved = self.documents_dir.joinpath(*key.parts).resolve()
        if not resolved.is_relative_to(self.documents_dir):
            raise UnsafeStorageKeyError("storage key escapes the documents directory")
        return resolved

    async def store(
        self,
        upload: AsyncUpload,
        *,
        max_size_bytes: int,
        company_id: UUID,
        company_slug: str,
        company_name: str,
    ) -> DocumentModel:
        """Stream, validate, hash, move, and persist one document upload."""

        temporary_path: Path | None = None
        destination: Path | None = None
        moved = False
        size_bytes = 0
        checksum = hashlib.sha256()

        try:
            metadata = validate_upload_metadata(
                filename=upload.filename,
                declared_media_type=upload.content_type,
            )
            document_id = uuid4()
            storage_key = f"{company_id.hex}/{document_id.hex}{metadata.extension}"
            destination = self.absolute_path(storage_key)
            self._ensure_directory(self.documents_dir)
            incoming_dir = self.documents_dir / ".incoming"
            self._ensure_directory(incoming_dir)
            file_descriptor, temporary_name = mkstemp(
                prefix="upload-", suffix=".tmp", dir=incoming_dir
            )
            temporary_path = Path(temporary_name)
            os.chmod(temporary_path, TEMPORARY_FILE_MODE)
            with os.fdopen(file_descriptor, "wb") as target:
                while chunk := await upload.read(READ_CHUNK_SIZE):
                    size_bytes += len(chunk)
                    if size_bytes > max_size_bytes:
                        raise UploadTooLargeError(
                            f"The uploaded document exceeds {max_size_bytes} bytes"
                        )
                    checksum.update(chunk)
                    target.write(chunk)
                target.flush()
                os.fsync(target.fileno())
            if size_bytes == 0:
                raise EmptyDocumentError("The uploaded document is empty")
            validate_stored_format(temporary_path, metadata.extension)
            digest = checksum.hexdigest()
            await self.antivirus_scanner.scan(
                AntivirusScanRequest(
                    path=temporary_path,
                    filename=metadata.filename,
                    media_type=metadata.media_type,
                    size_bytes=size_bytes,
                    sha256=digest,
                )
            )

            self._ensure_directory(destination.parent)
            if destination.exists():  # pragma: no cover - UUID collision guard
                raise FileExistsError("generated document storage key already exists")
            os.replace(temporary_path, destination)
            os.chmod(destination, STORED_FILE_MODE)
            moved = True

            with self.session_factory.begin() as session:
                company = CompanyRepository(session).get(company_id)
                if company is None:
                    CompanyRepository(session).add(
                        CompanyModel(
                            id=company_id,
                            slug=company_slug,
                            display_name=company_name,
                        )
                    )
                document = DocumentRepository(session).add(
                    DocumentModel(
                        id=document_id,
                        company_id=company_id,
                        uploaded_by_user_id=None,
                        original_filename=metadata.filename,
                        media_type=metadata.media_type,
                        size_bytes=size_bytes,
                        sha256=digest,
                        storage_key=storage_key,
                    )
                )
            self.metrics.record_success(size_bytes)
            return document
        except BaseException as error:
            self.metrics.record_failure(type(error).__name__)
            if temporary_path is not None:
                with suppress(OSError):
                    temporary_path.unlink()
            if moved and destination is not None:
                with suppress(OSError):
                    destination.unlink()
            raise
