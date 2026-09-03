from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from contracts import ContractValidationError, validate_review_result


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "contracts" / "examples"


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as source:
        return json.load(source)


class ReviewResultContractTests(unittest.TestCase):
    def test_valid_examples(self) -> None:
        for filename in ("success.json", "failure.json"):
            with self.subTest(filename=filename):
                validate_review_result(load_json(EXAMPLES / filename))

    def test_invalid_examples(self) -> None:
        invalid_dir = EXAMPLES / "invalid"
        for fixture in sorted(invalid_dir.glob("*.json")):
            with self.subTest(filename=fixture.name):
                with self.assertRaises(ContractValidationError):
                    validate_review_result(load_json(fixture))

    def test_duplicate_finding_ids_are_rejected(self) -> None:
        payload = load_json(EXAMPLES / "success.json")
        payload["findings"][1]["id"] = payload["findings"][0]["id"]
        with self.assertRaisesRegex(ContractValidationError, "must be unique"):
            validate_review_result(payload)

    def test_returned_count_must_match_findings(self) -> None:
        payload = load_json(EXAMPLES / "success.json")
        payload["summary"]["returned_findings"] = 1
        with self.assertRaisesRegex(ContractValidationError, "does not match findings length"):
            validate_review_result(payload)

    def test_severity_counts_must_match_findings(self) -> None:
        payload = load_json(EXAMPLES / "success.json")
        payload["summary"]["high"] = 0
        with self.assertRaisesRegex(ContractValidationError, "summary.high"):
            validate_review_result(payload)

    def test_candidate_counters_are_ordered(self) -> None:
        payload = load_json(EXAMPLES / "success.json")
        payload["summary"]["verified_candidates"] = 5
        with self.assertRaisesRegex(ContractValidationError, "Candidate counters"):
            validate_review_result(payload)

    def test_cyrillic_round_trip(self) -> None:
        payload = load_json(EXAMPLES / "success.json")
        expected = payload["findings"][0]["quote"]
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "результат.json"
            with target.open("w", encoding="utf-8") as output:
                json.dump(payload, output, ensure_ascii=False, indent=2)
            restored = load_json(target)
        self.assertEqual(restored["findings"][0]["quote"], expected)
        validate_review_result(restored)

    def test_optional_minor_extension_is_accepted(self) -> None:
        payload = copy.deepcopy(load_json(EXAMPLES / "success.json"))
        payload["schema_version"] = "1.1"
        payload["future_optional_field"] = {"enabled": True}
        validate_review_result(payload)


if __name__ == "__main__":
    unittest.main()
