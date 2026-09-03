"""Antivirus extension point for document storage."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class AntivirusRejectedError(ValueError):
    """Raised by a scanner when an upload must not enter permanent storage."""


@dataclass(frozen=True)
class AntivirusScanRequest:
    """Metadata supplied to a scanner; callers must not log the file content."""

    path: Path
    filename: str
    media_type: str
    size_bytes: int
    sha256: str


class AntivirusScanner(Protocol):
    """Pluggable asynchronous scanner contract."""

    async def scan(self, request: AntivirusScanRequest) -> None: ...


class DisabledAntivirusScanner:
    """Explicit MVP default; production can inject ClamAV or an internal scanner."""

    async def scan(self, request: AntivirusScanRequest) -> None:
        return None


disabled_antivirus_scanner = DisabledAntivirusScanner()


def get_antivirus_scanner() -> AntivirusScanner:
    """FastAPI dependency hook overridden when a real scanner is configured."""

    return disabled_antivirus_scanner
