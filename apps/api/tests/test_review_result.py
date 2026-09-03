import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from docreview_api.models import ReviewResultProjectionError, prepare_review_result_snapshot

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[3]
EXAMPLES_DIRECTORY = REPOSITORY_DIRECTORY / "contracts" / "examples"


def load_example(filename: str) -> dict[str, Any]:
    return json.loads((EXAMPLES_DIRECTORY / filename).read_text(encoding="utf-8"))


def test_completed_result_keeps_raw_payload_and_projects_findings() -> None:
    payload = load_example("success.json")
    payload["future_extension"] = {"trace": ["stage-1", {"score": 0.73}]}

    snapshot = prepare_review_result_snapshot(
        payload,
        expected_document_sha256=payload["document"]["sha256"],
    )

    assert snapshot.raw_result == payload
    assert snapshot.raw_result["future_extension"] == payload["future_extension"]
    assert snapshot.status == "completed"
    assert snapshot.run_id == payload["run_id"]
    assert snapshot.document_sha256 == payload["document"]["sha256"]
    assert len(snapshot.findings) == 2
    assert [finding.ordinal for finding in snapshot.findings] == [0, 1]
    assert [finding.core_finding_id for finding in snapshot.findings] == [
        "finding-001",
        "finding-002",
    ]


def test_projection_preserves_finding_values_without_rewriting() -> None:
    payload = load_example("success.json")
    source = payload["findings"][0]

    finding = prepare_review_result_snapshot(
        payload,
        expected_document_sha256=payload["document"]["sha256"],
    ).findings[0]

    assert finding.defect_id == source["defect_id"]
    assert finding.severity == source["severity"]
    assert finding.confidence == source["confidence"]
    assert finding.location == source["location"]
    assert finding.quote == source["quote"]
    assert finding.problem == source["problem"]
    assert finding.clarification == source["clarification"]
    assert finding.detected_by == tuple(source["detected_by"])


def test_completed_result_extracts_reproducibility_versions() -> None:
    payload = load_example("success.json")

    versions = prepare_review_result_snapshot(
        payload,
        expected_document_sha256=payload["document"]["sha256"],
    ).versions

    assert versions.schema_version == payload["schema_version"]
    assert versions.core_version == payload["engine"]["version"]
    assert versions.review_pack_id == payload["review_pack"]["id"]
    assert versions.review_pack_version == payload["review_pack"]["version"]
    assert versions.model_name == payload["model"]["name"]
    assert versions.prompt_versions == payload["model"]["prompt_versions"]


def test_snapshot_is_detached_from_mutable_caller_payload() -> None:
    payload = load_example("success.json")
    original = deepcopy(payload)
    snapshot = prepare_review_result_snapshot(
        payload,
        expected_document_sha256=payload["document"]["sha256"],
    )

    payload["findings"][0]["problem"] = "rewritten"
    payload["model"]["prompt_versions"]["data_logic"] = "999"

    assert snapshot.raw_result == original
    assert snapshot.findings[0].problem == original["findings"][0]["problem"]
    assert snapshot.versions.prompt_versions == original["model"]["prompt_versions"]


def test_failed_result_is_stored_whole_without_invented_versions() -> None:
    payload = load_example("failure.json")
    document_sha256 = "A" * 64

    snapshot = prepare_review_result_snapshot(
        payload,
        expected_document_sha256=document_sha256,
    )

    assert snapshot.raw_result == payload
    assert snapshot.status == "failed"
    assert snapshot.document_sha256 == document_sha256.lower()
    assert snapshot.findings == ()
    assert snapshot.versions.schema_version == payload["schema_version"]
    assert snapshot.versions.core_version is None
    assert snapshot.versions.review_pack_id is None
    assert snapshot.versions.review_pack_version is None
    assert snapshot.versions.model_name is None
    assert snapshot.versions.prompt_versions == {}


def test_document_hash_mismatch_is_rejected() -> None:
    payload = load_example("success.json")

    with pytest.raises(ReviewResultProjectionError, match="does not match"):
        prepare_review_result_snapshot(payload, expected_document_sha256="f" * 64)


@pytest.mark.parametrize("document_sha256", ["", "not-a-hash", "g" * 64])
def test_expected_document_hash_must_be_valid(document_sha256: str) -> None:
    with pytest.raises(ReviewResultProjectionError, match="64 hex"):
        prepare_review_result_snapshot(
            load_example("failure.json"),
            expected_document_sha256=document_sha256,
        )


def test_unrecognized_status_is_rejected() -> None:
    payload = load_example("failure.json")
    payload["status"] = "running"

    with pytest.raises(ReviewResultProjectionError, match="completed or failed"):
        prepare_review_result_snapshot(payload, expected_document_sha256="0" * 64)


def test_incomplete_completed_result_is_rejected_before_projection() -> None:
    payload = load_example("success.json")
    del payload["findings"][0]["location"]

    with pytest.raises(ReviewResultProjectionError, match="location must be an object"):
        prepare_review_result_snapshot(
            payload,
            expected_document_sha256=payload["document"]["sha256"],
        )
