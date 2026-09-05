"""Tenant-scoped and filesystem-safe Review Pack catalog."""

from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any
from uuid import UUID

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from docreview_api.db.models import CompanyModel, ReviewPackReferenceModel


@dataclass(frozen=True, slots=True)
class ReviewPackSnapshot:
    id: UUID
    company_name: str
    display_name: str
    document_type: str
    version: str
    description: str


@dataclass(frozen=True, slots=True)
class ReviewPackManifest:
    """Validated, presentation-safe metadata owned by a Review Pack."""

    pack_key: str
    version: str
    display_name: str
    document_type: str
    description: str


@dataclass(frozen=True, slots=True)
class DiscoveredReviewPack:
    """One valid manifest found under the server-controlled catalog root."""

    locator: str
    manifest: ReviewPackManifest


_MANIFEST_FILENAMES = ("pack.yaml", "pack.yml", "pack.json")
_MAX_MANIFEST_BYTES = 64 * 1024


def _required_text(value: Any, *, max_length: int) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized or len(normalized) > max_length:
        return None
    return normalized


def _resolve_locator(review_packs_root: Path, locator: str) -> Path | None:
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
        root = review_packs_root.resolve()
        candidate = root.joinpath(*posix.parts).resolve()
        if not candidate.is_relative_to(root):
            return None
        if candidate.is_file():
            return candidate if candidate.name.casefold() in _MANIFEST_FILENAMES else None
        if not candidate.is_dir():
            return None
        return next(
            (
                manifest
                for filename in _MANIFEST_FILENAMES
                if (manifest := candidate / filename).is_file()
            ),
            None,
        )
    except OSError:
        return None


def load_review_pack_manifest(
    review_packs_root: Path,
    locator: str,
) -> ReviewPackManifest | None:
    """Load only bounded metadata from a server-approved relative locator."""

    manifest_path = _resolve_locator(review_packs_root, locator)
    if manifest_path is None:
        return None
    try:
        if manifest_path.stat().st_size > _MAX_MANIFEST_BYTES:
            return None
        payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        return None
    if not isinstance(payload, dict):
        return None

    pack_key = _required_text(payload.get("id"), max_length=255)
    version = _required_text(payload.get("version"), max_length=100)
    display_name = _required_text(payload.get("name"), max_length=255)
    document_type = _required_text(payload.get("document_type"), max_length=100)
    description = _required_text(payload.get("description"), max_length=2000)
    if (
        pack_key is None
        or version is None
        or display_name is None
        or document_type is None
        or description is None
    ):
        return None
    return ReviewPackManifest(
        pack_key=pack_key,
        version=version,
        display_name=display_name,
        document_type=document_type,
        description=description,
    )


def discover_review_pack_manifests(
    review_packs_root: Path,
) -> tuple[DiscoveredReviewPack, ...]:
    """Scan the fixed ``<pack-id>/<version>/pack.*`` catalog shape safely."""

    try:
        root = review_packs_root.resolve()
        pack_directories = sorted(root.iterdir(), key=lambda path: path.name.casefold())
    except OSError:
        return ()

    discovered: list[DiscoveredReviewPack] = []
    for pack_directory in pack_directories:
        try:
            if pack_directory.name.startswith(".") or not pack_directory.is_dir():
                continue
            version_directories = sorted(
                pack_directory.iterdir(),
                key=lambda path: path.name.casefold(),
            )
        except OSError:
            continue
        for version_directory in version_directories:
            try:
                if version_directory.name.startswith(".") or not version_directory.is_dir():
                    continue
                locator = version_directory.relative_to(root).as_posix()
            except (OSError, ValueError):
                continue
            manifest = load_review_pack_manifest(root, locator)
            if (
                manifest is None
                or manifest.pack_key != pack_directory.name
                or manifest.version != version_directory.name
            ):
                continue
            discovered.append(DiscoveredReviewPack(locator=locator, manifest=manifest))
    return tuple(discovered)


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
            company = session.get(CompanyModel, company_id)
            if company is None or not company.is_active or not company.display_name.strip():
                return ()
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
            snapshots = tuple(
                snapshot
                for record in records
                if (snapshot := self._public_snapshot(record, company.display_name.strip()))
                is not None
            )
            return tuple(
                sorted(
                    snapshots,
                    key=lambda item: (
                        item.display_name.casefold(),
                        item.version,
                        str(item.id),
                    ),
                )
            )

    def _public_snapshot(
        self,
        record: ReviewPackReferenceModel,
        company_name: str,
    ) -> ReviewPackSnapshot | None:
        manifest = load_review_pack_manifest(self._review_packs_root, record.locator)
        if (
            manifest is None
            or manifest.pack_key != record.pack_key
            or manifest.version != record.version
        ):
            return None
        return ReviewPackSnapshot(
            id=record.id,
            company_name=company_name,
            display_name=manifest.display_name,
            document_type=manifest.document_type,
            version=manifest.version,
            description=manifest.description,
        )
