from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from docreview_api.services import (
    RunWorkspaceAlreadyExistsError,
    RunWorkspaceManager,
    RunWorkspaceNotReadyError,
    UnsafeRunPathError,
)


def test_prepare_creates_complete_run_layout(tmp_path: Path) -> None:
    runs_root = tmp_path / "storage" / "runs"

    workspace = RunWorkspaceManager(runs_root).prepare("review-123")

    assert workspace.root == (runs_root / "review-123").resolve()
    assert workspace.input_dir == workspace.root / "input"
    assert workspace.output_dir == workspace.root / "output"
    assert workspace.artifacts_dir == workspace.root / "artifacts"
    assert all(
        path.is_dir()
        for path in (workspace.input_dir, workspace.output_dir, workspace.artifacts_dir)
    )
    assert not list(runs_root.glob(".preparing-*"))


def test_different_runs_are_isolated(tmp_path: Path) -> None:
    manager = RunWorkspaceManager(tmp_path / "runs")
    first = manager.prepare("review-one")
    second = manager.prepare("review-two")

    first_result = first.resolve("output/result.json")
    second_result = second.resolve("output/result.json")
    first_result.write_text("first", encoding="utf-8")
    second_result.write_text("second", encoding="utf-8")

    assert first.root != second.root
    assert first_result.read_text(encoding="utf-8") == "first"
    assert second_result.read_text(encoding="utf-8") == "second"


def test_parallel_prepare_allows_only_one_owner_for_same_run(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"

    def prepare() -> str:
        try:
            RunWorkspaceManager(runs_root).prepare("review-shared")
        except RunWorkspaceAlreadyExistsError:
            return "existing"
        return "created"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _: prepare(), range(2)))

    assert sorted(outcomes) == ["created", "existing"]
    assert set(path.name for path in (runs_root / "review-shared").iterdir()) == {
        "input",
        "output",
        "artifacts",
    }
    assert not list(runs_root.glob(".preparing-*"))


def test_existing_workspace_is_not_reused_by_prepare(tmp_path: Path) -> None:
    manager = RunWorkspaceManager(tmp_path / "runs")
    original = manager.prepare("review-once")

    with pytest.raises(RunWorkspaceAlreadyExistsError):
        manager.prepare("review-once")

    assert manager.open("review-once") == original


@pytest.mark.parametrize(
    "run_id",
    ["", ".", "..", "../other", "nested/run", "C:\\other", "/absolute", "x" * 129],
)
def test_unsafe_run_ids_are_rejected(tmp_path: Path, run_id: str) -> None:
    manager = RunWorkspaceManager(tmp_path / "runs")

    with pytest.raises(UnsafeRunPathError):
        manager.prepare(run_id)


@pytest.mark.parametrize(
    "relative_path",
    [
        "../other/result.json",
        "output/../../other.json",
        "/absolute/result.json",
        "C:\\result.json",
        "unknown/result.json",
        "",
    ],
)
def test_workspace_rejects_paths_outside_allocated_directories(
    tmp_path: Path, relative_path: str
) -> None:
    workspace = RunWorkspaceManager(tmp_path / "runs").prepare("review-safe")

    with pytest.raises(UnsafeRunPathError):
        workspace.resolve(relative_path)


def test_workspace_rejects_symlink_escape_when_supported(tmp_path: Path) -> None:
    workspace = RunWorkspaceManager(tmp_path / "runs").prepare("review-link")
    outside = tmp_path / "outside"
    outside.mkdir()
    link = workspace.artifacts_dir / "external"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are not available for this Windows user")

    with pytest.raises(UnsafeRunPathError):
        workspace.resolve("artifacts/external/secret.txt")


def test_open_rejects_missing_or_incomplete_workspace(tmp_path: Path) -> None:
    manager = RunWorkspaceManager(tmp_path / "runs")
    manager.runs_root.mkdir(parents=True)

    with pytest.raises(RunWorkspaceNotReadyError):
        manager.open("review-missing")

    incomplete = manager.runs_root / "review-incomplete"
    incomplete.mkdir()
    (incomplete / "input").mkdir()
    with pytest.raises(RunWorkspaceNotReadyError):
        manager.open("review-incomplete")
