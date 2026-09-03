import json
from pathlib import Path
from typing import Any

from contracts.validate_contract import validate_review_result

from docreview_mock.success_fixtures import build_success_scenarios

FIXTURES_DIRECTORY = Path(__file__).resolve().parents[1] / "fixtures" / "success"
EXPECTED_COUNTS = {
    "empty.json": 0,
    "standard-12.json": 12,
    "maximum-20.json": 20,
}


def load_fixture(filename: str) -> dict[str, Any]:
    return json.loads((FIXTURES_DIRECTORY / filename).read_text(encoding="utf-8"))


def test_checked_in_fixtures_match_deterministic_generator() -> None:
    assert {filename: load_fixture(filename) for filename in EXPECTED_COUNTS} == (
        build_success_scenarios()
    )


def test_success_fixtures_follow_contract_and_required_counts() -> None:
    for filename, expected_count in EXPECTED_COUNTS.items():
        payload = load_fixture(filename)
        validate_review_result(payload)
        assert len(payload["findings"]) == expected_count
        assert payload["summary"]["returned_findings"] == expected_count

    assert 10 <= len(load_fixture("standard-12.json")["findings"]) <= 15
    assert len(load_fixture("maximum-20.json")["findings"]) == 20


def test_populated_fixtures_cover_severities_locations_and_russian_text() -> None:
    findings = load_fixture("maximum-20.json")["findings"]

    assert {finding["severity"] for finding in findings} == {
        "critical",
        "high",
        "medium",
        "low",
    }
    assert any("table" not in finding["location"] for finding in findings)
    assert any(
        finding["location"].get("table")
        and finding["location"].get("row") is not None
        and finding["location"].get("column") is not None
        for finding in findings
    )
    assert all(len(finding["location"]["section_path"]) >= 5 for finding in findings)
    assert any(any(ord(character) > 127 for character in finding["quote"]) for finding in findings)
    assert len(findings) <= 20
