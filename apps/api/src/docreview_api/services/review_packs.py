"""Tenant-scoped and filesystem-safe Review Pack catalog."""

from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from docreview_api.db.models import ReviewPackReferenceModel


@dataclass(frozen=True, slots=True)
class ReviewPackSnapshot:
    id: UUID
    display_name: str
    document_type: str
    version: str


class ReviewPackCatalogService:
    """Expose only active pack references resolvable inside the configured root."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        review_packs_root: Path,
    ) -> None:
        self._session_factory = session_factory
        self._review_packs_root = review_packs_root.resolve()

    def list_available(self, *, company_id: UUID) -> tuple[ReviewPackSnapshot, ...]:
        with self._session_factory() as session:
            records = session.scalars(
                select(ReviewPackReferenceModel)
                .where(
                    ReviewPackReferenceModel.company_id == company_id,
                    ReviewPackReferenceModel.is_active.is_(True),
                )
                .order_by(
                    ReviewPackReferenceModel.display_name,
                    ReviewPackReferenceModel.version,
                    ReviewPackReferenceModel.id,
                )
            ).all()
            return tuple(
                snapshot
                for record in records
                if (snapshot := self._public_snapshot(record)) is not None
            )

    def _public_snapshot(self, record: ReviewPackReferenceModel) -> ReviewPackSnapshot | None:
        display_name = record.display_name.strip()
        document_type = record.document_type.strip()
        version = record.version.strip()
        if not display_name or not document_type or not version:
            return None
        if self._resolve_locator(record.locator) is None:
            return None
        return ReviewPackSnapshot(
            id=record.id,
            display_name=display_name,
            document_type=document_type,
            version=version,
        )

    def _resolve_locator(self, locator: str) -> Path | None:
        posix = PurePosixPath(locator)
        if (
            not locator
            or locator == "."
            or posix.is_absolute()
            or PureWindowsPath(locator).is_absolute()
            or "\\" in locator
            or ".." in posix.parts
        ):
            return None
        try:
            candidate = self._review_packs_root.joinpath(*posix.parts).resolve()
            if not candidate.is_relative_to(self._review_packs_root):
                return None
            if candidate.is_file():
                return (
                    candidate if candidate.suffix.casefold() in {".yaml", ".yml", ".json"} else None
                )
            if candidate.is_dir() and any(candidate.iterdir()):
                return candidate
        except OSError:
            return None
        return None
