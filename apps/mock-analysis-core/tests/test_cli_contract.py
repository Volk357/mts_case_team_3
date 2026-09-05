"""End-to-end process contract tests for the installed mock executable."""

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from contracts.validate_contract import ContractValidationError, validate_review_result


@dataclass(frozen=True)
class ProcessResult:
    completed: subprocess.CompletedProcess[str]
    output: Path
    run_id: str


def _executable() -> Path:
    executable_name = "docreview-mock.exe" if sys.platform == "win32" else "docreview-mock"
    return Path(sys.executable).with_name(executable_name)


def _run_scenario(tmp_path: Path, scenario: str) -> ProcessResult:
    document = tmp_path / "требования.pdf"
    document.write_text("Конфиденциальное содержимое документа", encoding="utf-8")
    review_pack = tmp_path / "company-review-pack"
    review_pack.mkdir()
    output = tmp_path / "result.json"
    run_id = f"contract-{scenario}-рус"
    environment = os.environ.copy()
    environment.update(
        {
            "DOCREVIEW_MOCK_PROFILE": "test",
            "DOCREVIEW_MOCK_SCENARIO": scenario,
            "DOCREVIEW_MOCK_DELAY_MS": "0",
        }
    )

    completed = subprocess.run(
        [
            _executable(),
            "analyze",
            "--file",
            document,
            "--pack",
            review_pack,
            "--run-id",
            run_id,
            "--output",
            output,
        ],
        check=False,
        capture_output=True,
        encoding="utf-8",
        env=environment,
        timeout=10,
    )
    return ProcessResult(completed=completed, output=output, run_id=run_id)


SCENARIO_EXIT_CODES = {
    "empty": 0,
    "standard-12": 0,
    "maximum-20": 0,
    "document-parse-error": 3,
    "review-pack-not-found": 4,
    "model-unavailable": 5,
    "invalid-json": 6,
    "incompatible-schema-version": 0,
    "crash": 7,
    "timeout": 8,
    "missing-result-after-success": 0,
}
NO_RESULT_SCENARIOS = {"crash", "missing-result-after-success"}
INVALID_RESULT_SCENARIOS = {"invalid-json", "incompatible-schema-version"}


@pytest.mark.parametrize(("scenario", "exit_code"), SCENARIO_EXIT_CODES.items())
def test_installed_cli_obeys_scenario_process_contract(
    tmp_path: Path,
    scenario: str,
    exit_code: int,
) -> None:
    result = _run_scenario(tmp_path, scenario)
    completed = result.completed

    assert completed.returncode == exit_code
    assert completed.stderr.startswith("mock:")
    assert "Конфиденциальное содержимое документа" not in completed.stderr

    if scenario in NO_RESULT_SCENARIOS:
        assert completed.stdout == ""
        assert not result.output.exists()
        return

    assert completed.stdout != ""
    assert result.output.read_text(encoding="utf-8") == completed.stdout

    if scenario == "invalid-json":
        with pytest.raises(json.JSONDecodeError):
            json.loads(completed.stdout)
        return

    payload = json.loads(completed.stdout)
    assert payload["run_id"] == result.run_id
    if scenario == "incompatible-schema-version":
        with pytest.raises(ContractValidationError, match="schema_version"):
            validate_review_result(payload)
        return

    validate_review_result(payload)
    if payload["status"] == "completed":
        assert len(payload["findings"]) <= 20


def test_installed_cli_covers_every_contract_exit_code(tmp_path: Path) -> None:
    observed = set(SCENARIO_EXIT_CODES.values())
    completed = subprocess.run(
        [_executable(), "analyze"],
        check=False,
        capture_output=True,
        encoding="utf-8",
        timeout=10,
    )

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert "required" in completed.stderr
    observed.add(completed.returncode)
    assert observed == {0, 2, 3, 4, 5, 6, 7, 8}


@pytest.mark.parametrize("scenario", sorted(INVALID_RESULT_SCENARIOS))
def test_invalid_contract_results_are_still_written_verbatim(
    tmp_path: Path,
    scenario: str,
) -> None:
    result = _run_scenario(tmp_path, scenario)

    assert result.output.is_file()
    assert result.output.read_bytes().decode("utf-8") == result.completed.stdout
