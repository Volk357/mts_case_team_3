import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from docreview_mock import cli
from docreview_mock.cli import main


def test_installed_executable_exposes_version_command() -> None:
    executable_name = "docreview-mock.exe" if sys.platform == "win32" else "docreview-mock"
    executable = Path(sys.executable).with_name(executable_name)
    completed = subprocess.run(
        [executable, "version"],
        check=False,
        capture_output=True,
        encoding="utf-8",
    )

    assert completed.returncode == 0
    assert completed.stderr == ""
    assert json.loads(completed.stdout)["version"] == "0.1.0"


def test_version_writes_machine_readable_json_only_to_stdout(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["version"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.err == ""
    assert json.loads(captured.out) == {
        "name": "docreview-mock-analysis-core",
        "version": "0.1.0",
        "schema_version": "1.0",
    }


def test_analyze_accepts_full_contract_and_atomically_writes_utf8_json(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = tmp_path / "требования.pdf"
    document.write_text("Русский текст документа", encoding="utf-8")
    review_pack = tmp_path / "корпоративные-правила"
    review_pack.mkdir()
    model_config = tmp_path / "model-config.yaml"
    model_config.write_text("base_url: http://localhost", encoding="utf-8")
    output = tmp_path / "nested" / "result.json"
    artifacts = tmp_path / "artifacts"

    exit_code = main(
        [
            "analyze",
            "--file",
            str(document),
            "--pack",
            str(review_pack),
            "--model-config",
            str(model_config),
            "--run-id",
            "review-русский-123",
            "--output",
            str(output),
            "--artifacts-dir",
            str(artifacts),
            "--include-rejected",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "mock analysis completed" not in captured.out
    result: dict[str, Any] = json.loads(captured.out)
    assert result["status"] == "completed"
    assert result["run_id"] == "review-русский-123"
    assert result["document"]["filename"] == "требования.pdf"
    assert output.read_text(encoding="utf-8") == captured.out
    assert "mock analysis completed" in captured.err
    assert list(output.parent.glob(f".{output.name}.*.tmp")) == []


def test_analyze_writes_json_to_stdout_without_output_option(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = tmp_path / "document"
    document.write_text("content", encoding="utf-8")
    review_pack = tmp_path / "pack.yaml"
    review_pack.write_text("version: 1", encoding="utf-8")

    exit_code = main(
        [
            "analyze",
            "--file",
            str(document),
            "--pack",
            str(review_pack),
            "--run-id",
            "review-123",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    result = json.loads(captured.out)
    assert result["status"] == "completed"
    assert result["document"]["document_type"] == "unknown"


@pytest.mark.parametrize(
    ("missing", "expected_code", "expected_error"),
    [
        ("document", 3, "document is unavailable"),
        ("pack", 4, "review pack is unavailable"),
    ],
)
def test_missing_inputs_use_contract_exit_codes(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    missing: str,
    expected_code: int,
    expected_error: str,
) -> None:
    document = tmp_path / "document.txt"
    review_pack = tmp_path / "pack"
    if missing != "document":
        document.write_text("content", encoding="utf-8")
    if missing != "pack":
        review_pack.mkdir()

    exit_code = main(
        [
            "analyze",
            "--file",
            str(document),
            "--pack",
            str(review_pack),
            "--run-id",
            "review-123",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == expected_code
    assert captured.out == ""
    assert expected_error in captured.err


def test_invalid_arguments_use_contract_exit_code_two(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as error:
        main(["analyze"])
    captured = capsys.readouterr()

    assert error.value.code == 2
    assert captured.out == ""
    assert "required" in captured.err


def test_empty_run_id_is_rejected(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as error:
        main(["analyze", "--file", "document", "--pack", "pack", "--run-id", ""])
    captured = capsys.readouterr()

    assert error.value.code == 2
    assert "run id must contain" in captured.err


def test_atomic_writer_removes_temporary_file_after_replace_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "result.json"

    def fail_replace(source: Path, destination: Path) -> None:
        raise OSError(f"cannot replace {source} with {destination}")

    monkeypatch.setattr(cli.os, "replace", fail_replace)

    with pytest.raises(OSError, match="cannot replace"):
        cli._write_atomically(output, "{}\n")

    assert not output.exists()
    assert list(tmp_path.iterdir()) == []
