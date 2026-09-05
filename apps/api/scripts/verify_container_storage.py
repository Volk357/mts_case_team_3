"""Fail fast when shared container storage has unsafe ownership or access."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _configured_writable_directories() -> tuple[Path, ...]:
    heartbeat = Path(
        os.environ.get("DOCREVIEW_WORKER_HEARTBEAT_PATH", "/app/data/state/worker-heartbeat")
    )
    return (
        Path(os.environ.get("DOCREVIEW_DOCUMENTS_DIR", "/app/data/documents")),
        Path(os.environ.get("DOCREVIEW_RUNS_DIR", "/app/data/runs")),
        Path(os.environ.get("DOCREVIEW_ARTIFACTS_DIR", "/app/data/artifacts")),
        heartbeat.parent,
    )


def _configured_review_packs_directory() -> Path:
    return Path(os.environ.get("DOCREVIEW_REVIEW_PACKS_DIR", "/app/review-packs"))


def _verify_writable_directory(path: Path) -> str | None:
    if not path.is_dir():
        return f"required storage directory does not exist: {path}"

    stat = path.stat()
    if stat.st_uid != os.getuid() or stat.st_gid != os.getgid():
        return (
            f"storage directory {path} is owned by {stat.st_uid}:{stat.st_gid}; "
            f"expected {os.getuid()}:{os.getgid()}"
        )

    probe = path / f".storage-check-{os.getpid()}"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as error:
        return f"storage directory is not writable: {path}: {error}"
    return None


def _verify_review_packs_read_only() -> str | None:
    review_packs_directory = _configured_review_packs_directory()
    if not review_packs_directory.is_dir():
        return f"Review Packs directory does not exist: {review_packs_directory}"
    if not any(review_packs_directory.iterdir()):
        return f"Review Packs directory is empty: {review_packs_directory}"

    probe = review_packs_directory / f".storage-check-{os.getpid()}"
    try:
        probe.write_text("must fail", encoding="utf-8")
    except OSError:
        return None
    finally:
        if probe.exists():
            probe.unlink()
    return f"Review Packs directory is writable: {review_packs_directory}"


def main() -> int:
    errors = [
        error
        for error in (
            *(_verify_writable_directory(path) for path in _configured_writable_directories()),
            _verify_review_packs_read_only(),
        )
        if error is not None
    ]
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 2
    print(f"Storage permissions are valid for uid:gid {os.getuid()}:{os.getgid()}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
