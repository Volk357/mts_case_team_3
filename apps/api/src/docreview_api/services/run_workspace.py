"""Isolated filesystem workspaces for Analysis Core runs."""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from tempfile import mkdtemp

DIRECTORY_MODE = 0o750
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
WORKSPACE_DIRECTORIES = ("input", "output", "artifacts")


class RunWorkspaceError(ValueError):
    """Base error for unsafe or unusable run workspaces."""


class UnsafeRunPathError(RunWorkspaceError):
    """A run identifier or relative path could escape its allocated root."""


class RunWorkspaceAlreadyExistsError(RunWorkspaceError):
    """A workspace has already been allocated for this run identifier."""


class RunWorkspaceNotReadyError(RunWorkspaceError):
    """A persisted workspace is missing or does not have the required layout."""


@dataclass(frozen=True, slots=True)
class RunWorkspace:
    """Paths owned exclusively by one Analysis Core run."""

    run_id: str
    root: Path
    input_dir: Path
    output_dir: Path
    artifacts_dir: Path

    def resolve(self, relative_path: str | Path) -> Path:
        """Resolve a safe POSIX-style path inside this workspace."""

        raw_path = str(relative_path)
        posix_path = PurePosixPath(raw_path)
        if (
            not raw_path
            or "\\" in raw_path
            or posix_path.is_absolute()
            or PureWindowsPath(raw_path).is_absolute()
            or ".." in posix_path.parts
            or not posix_path.parts
            or posix_path.parts[0] not in WORKSPACE_DIRECTORIES
        ):
            raise UnsafeRunPathError("path must stay inside an allocated workspace directory")

        workspace_root = self.root.resolve()
        candidate = workspace_root.joinpath(*posix_path.parts).resolve()
        if not candidate.is_relative_to(workspace_root):
            raise UnsafeRunPathError("path escapes the allocated run workspace")
        return candidate


class RunWorkspaceManager:
    """Atomically allocate and reopen run-scoped filesystem directories."""

    def __init__(self, runs_root: Path) -> None:
        self.runs_root = runs_root.resolve()

    def prepare(self, run_id: str) -> RunWorkspace:
        """Create a complete workspace; never reuse an existing run directory."""

        run_id = self._validate_run_id(run_id)
        self._ensure_directory(self.runs_root)
        destination = self.runs_root / run_id
        if destination.exists() or destination.is_symlink():
            raise RunWorkspaceAlreadyExistsError(f"workspace for run {run_id} already exists")

        staging = Path(mkdtemp(prefix=f".preparing-{run_id}-", dir=self.runs_root))
        try:
            os.chmod(staging, DIRECTORY_MODE)
            for directory_name in WORKSPACE_DIRECTORIES:
                self._ensure_directory(staging / directory_name)
            try:
                os.rename(staging, destination)
            except OSError as error:
                if destination.exists() or destination.is_symlink():
                    raise RunWorkspaceAlreadyExistsError(
                        f"workspace for run {run_id} already exists"
                    ) from error
                raise
        finally:
            if staging.exists():
                shutil.rmtree(staging)

        return self.open(run_id)

    def open(self, run_id: str) -> RunWorkspace:
        """Open a previously prepared workspace without creating missing paths."""

        run_id = self._validate_run_id(run_id)
        root = self.runs_root / run_id
        if root.is_symlink() or not root.is_dir() or root.resolve().parent != self.runs_root:
            raise RunWorkspaceNotReadyError(f"workspace for run {run_id} is not ready")

        directories = tuple(root / name for name in WORKSPACE_DIRECTORIES)
        if any(path.is_symlink() or not path.is_dir() for path in directories):
            raise RunWorkspaceNotReadyError(f"workspace for run {run_id} is incomplete")
        return RunWorkspace(
            run_id=run_id,
            root=root.resolve(),
            input_dir=directories[0].resolve(),
            output_dir=directories[1].resolve(),
            artifacts_dir=directories[2].resolve(),
        )

    @staticmethod
    def _validate_run_id(run_id: str) -> str:
        if not isinstance(run_id, str) or RUN_ID_PATTERN.fullmatch(run_id) is None:
            raise UnsafeRunPathError("run_id must be a safe 1 to 128 character identifier")
        return run_id

    @staticmethod
    def _ensure_directory(path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        os.chmod(path, DIRECTORY_MODE)
