"""Read-side document use cases independent of HTTP transport."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from docreview_api.db.models import DocumentModel


class DocumentUnavailableError(LookupError):
    """A document is absent, deleted, or outside the requesting tenant."""


class DocumentFileUnavailableError(RuntimeError):
    """Document metadata exists but its private storage object is unavailable."""


@dataclass(frozen=True, slots=True)
class DocumentSnapshot:
    id: UUID
    filename: str
    size_bytes: int
    media_type: str
    created_at: datetime


class DocumentQueryService:
    """Return verified public metadata without exposing storage implementation."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        documents_root: Path,
    ) -> None:
        self._session_factory = session_factory
        self._documents_root = documents_root.resolve()

    def get(self, document_id: UUID, *, company_id: UUID) -> DocumentSnapshot:
        with self._session_factory() as session:
            statement = select(DocumentModel).where(
                DocumentModel.id == document_id,
                DocumentModel.company_id == company_id,
                DocumentModel.deleted_at.is_(None),
            )
            document = session.scalar(statement)
            if document is None:
                raise DocumentUnavailableError("document is unavailable")
            self._require_storage_object(document.storage_key, expected_size=document.size_bytes)
            created_at = document.created_at
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=UTC)
            return DocumentSnapshot(
                id=document.id,
                filename=document.original_filename,
                size_bytes=document.size_bytes,
                media_type=document.media_type,
                created_at=created_at.astimezone(UTC),
            )

    def _require_storage_object(self, storage_key: str, *, expected_size: int) -> None:
        key = PurePosixPath(storage_key)
        if (
            not storage_key
            or key.is_absolute()
            or PureWindowsPath(storage_key).is_absolute()
            or ".." in key.parts
            or "\\" in storage_key
        ):
            raise DocumentFileUnavailableError("document storage key is invalid")
        unresolved = self._documents_root.joinpath(*key.parts)
        resolved = unresolved.resolve()
        if (
            unresolved.is_symlink()
            or not resolved.is_relative_to(self._documents_root)
            or not resolved.is_file()
        ):
            raise DocumentFileUnavailableError("document storage object is unavailable")
        try:
            actual_size = resolved.stat().st_size
        except OSError as error:
            raise DocumentFileUnavailableError("document storage object cannot be read") from error
        if actual_size != expected_size:
            raise DocumentFileUnavailableError(
                "document storage object size does not match metadata"
            )
