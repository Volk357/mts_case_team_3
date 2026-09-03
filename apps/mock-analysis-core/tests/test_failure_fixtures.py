import json
from pathlib import Path
from typing import Any

import pytest
from contracts.validate_contract import ContractValidationError, validate_review_result

from docreview_mock.failure_fixtures import build_failure_manifest, build_failure_payloads

FIXTURES_DIRECTORY = Path(__file__).resolve().parents[1] / "fixtures" / "failure"
EXPECTED_SCENARIOS = {
    "document-parse-error",
    "review-pack-not-found",
    "model-unavailable",
    "invalid-json",
    "incompatible-schema-version",
    "timeout",
    "crash",
    "missing-result-after-success",
}


def load_text(filename: str) -> str:
    return (FIXTURES_DIRECTORY / filename).read_text(encoding="utf-8")


def test_checked_in_failure_fixtures_match_deterministic_generator() -> None:
    manifest = json.loads(load_text("manifest.json"))
    assert manifest == build_failure_manifest()

    for filename, expected in build_failure_payloads().items():
        actual = load_text(filename)
        if isinstance(expected, str):
            assert actual == expected + "\n"
        else:
            assert json.loads(actual) == expected


def test_manifest_covers_required_process_failures_and_exit_codes() -> None:
    manifest: dict[str, dict[str, Any]] = json.loads(load_text("manifest.json"))

    assert set(manifest) == EXPECTED_SCENARIOS
    assert manifest["document-parse-error"]["exit_code"] == 3
    assert manifest["review-pack-not-found"]["exit_code"] == 4
    assert manifest["model-unavailable"]["exit_code"] == 5
    assert manifest["invalid-json"]["exit_code"] == 6
    assert manifest["crash"]["exit_code"] == 7
    assert manifest["timeout"]["exit_code"] == 8
    assert manifest["missing-result-after-success"]["exit_code"] == 0
    assert manifest["timeout"]["delay_ms"] > 0


def test_structured_failure_results_follow_review_result_contract() -> None:
    manifest: dict[str, dict[str, Any]] = json.loads(load_text("manifest.json"))
    valid_scenarios = {
        "document-parse-error",
        "review-pack-not-found",
        "model-unavailable",
        "timeout",
    }

    for scenario in valid_scenarios:
        payload = json.loads(load_text(manifest[scenario]["result_file"]))
        validate_review_result(payload)
        assert payload["status"] == "failed"


def test_deliberately_invalid_outputs_are_rejected() -> None:
    with pytest.raises(json.JSONDecodeError):
        json.loads(load_text("invalid-json.txt"))

    incompatible = json.loads(load_text("incompatible-schema-version.json"))
    with pytest.raises(ContractValidationError, match="schema_version"):
        validate_review_result(incompatible)


def test_no_result_scenarios_have_no_stdout_fixture() -> None:
    manifest: dict[str, dict[str, Any]] = json.loads(load_text("manifest.json"))

    assert manifest["crash"]["result_file"] is None
    assert manifest["missing-result-after-success"]["result_file"] is None
