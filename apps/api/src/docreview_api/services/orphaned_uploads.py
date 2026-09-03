"""Explicit cleanup procedure for stale temporary and unreferenced upload files."""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from docreview_api.db.models import DocumentModel

_HEX_UUID = re.compile(r"^[0-9a-f]{32}$")
_DOCUMENT_FILE = re.compile(r"^[0-9a-f]{32}\.(?:pdf|docx)$")


@dataclass(frozen=True)
class OrphanCleanupReport:
    scanned_files: int
    deleted_temporary_files: int
    deleted_unreferenced_files: int
    failed_deletions: int


class OrphanedUploadCleaner:
    """Delete only old, recognized upload files when explicitly invoked."""

    def __init__(self, documents_dir: Path, session_factory: sessionmaker[Session]) -> None:
        self.documents_dir = documents_dir.resolve()
        self.session_factory = session_factory

    @staticmethod
    def _is_old(path: Path, cutoff_timestamp: float) -> bool:
        return path.stat().st_mtime <= cutoff_timestamp

    @staticmethod
    def _delete(path: Path) -> bool:
        try:
            path.unlink()
        except OSError:
            return False
        return True

    def cleanup(self, *, now: datetime, grace_period: timedelta) -> OrphanCleanupReport:
        """Run one idempotent cleanup pass without following symlinks."""

        if now.utcoffset() != timedelta(0):
            raise ValueError("now must be a timezone-aware UTC datetime")
        if grace_period <= timedelta(0):
            raise ValueError("grace_period must be positive")
        cutoff_timestamp = (now - grace_period).timestamp()
        scanned = 0
        deleted_temporary = 0
        deleted_unreferenced = 0
        failures = 0

        incoming_dir = self.documents_dir / ".incoming"
        if incoming_dir.is_dir() and not incoming_dir.is_symlink():
            for path in incoming_dir.glob("upload-*.tmp"):
                if not path.is_file() or path.is_symlink():
                    continue
                scanned += 1
                if self._is_old(path, cutoff_timestamp):
                    if self._delete(path):
                        deleted_temporary += 1
                    else:
                        failures += 1

        with self.session_factory() as session:
            referenced_keys = set(session.scalars(select(DocumentModel.storage_key)))
        if self.documents_dir.is_dir():
            for company_dir in self.documents_dir.iterdir():
                if (
                    not company_dir.is_dir()
                    or company_dir.is_symlink()
                    or not _HEX_UUID.fullmatch(company_dir.name)
                ):
                    continue
                for path in company_dir.iterdir():
                    if (
                        not path.is_file()
                        or path.is_symlink()
                        or not _DOCUMENT_FILE.fullmatch(path.name)
                    ):
                        continue
                    scanned += 1
                    storage_key = path.relative_to(self.documents_dir).as_posix()
                    if storage_key not in referenced_keys and self._is_old(path, cutoff_timestamp):
                        if self._delete(path):
                            deleted_unreferenced += 1
                        else:
                            failures += 1

        return OrphanCleanupReport(
            scanned_files=scanned,
            deleted_temporary_files=deleted_temporary,
            deleted_unreferenced_files=deleted_unreferenced,
            failed_deletions=failures,
        )
