"""Acceptance checks for the code-free second Review Pack profile."""

from pathlib import Path

import yaml

import check_formal
import docreview
import docx_text

REPOSITORY = Path(__file__).resolve().parents[1]
NET_PACK = REPOSITORY / "review-packs" / "mts-net" / "0.2"
GENERIC_PACK = REPOSITORY / "review-packs" / "generic-tech-spec" / "1.0"
GENERIC_DOCUMENT = (
    REPOSITORY / "examples" / "platform-showcase" / "generic-notification-service.docx"
)


def test_two_profiles_resolve_without_application_changes() -> None:
    net = docreview.resolve_pack(str(NET_PACK))
    generic = docreview.resolve_pack(str(GENERIC_PACK))

    assert net[:2] == ("mts-net", "0.2")
    assert generic[:2] == ("generic-tech-spec", "1.0")
    assert all(Path(path).is_file() for path in generic[2:5])
    assert generic[5] == []


def test_generic_profile_has_its_own_finding_categories() -> None:
    payload = yaml.safe_load((GENERIC_PACK / "defects.yaml").read_text(encoding="utf-8"))
    defect_ids = {item["id"] for item in payload["defects"]}

    assert {
        "AMBIGUOUS_REQUIREMENT",
        "INCOMPLETE_API_CONTRACT",
        "ERROR_HANDLING_UNDEFINED",
        "SECURITY_REQUIREMENT_GAP",
        "OBSERVABILITY_GAP",
        "ACCEPTANCE_CRITERIA_MISSING",
    } <= defect_ids


def test_generic_document_is_readable_and_triggers_pack_rules() -> None:
    text = docx_text.extract(str(GENERIC_DOCUMENT))
    config = check_formal.load_config(GENERIC_PACK / "template.yaml")
    findings = check_formal.run(text, config)["findings"]
    finding_ids = {item["defect_id"] for item in findings}

    assert "Техническое задание на сервис уведомлений" in text
    assert finding_ids == {"PLACEHOLDER_LEFT", "VAGUE_WORDING"}
    assert check_formal.verify_quotes({"findings": findings}, text) == []
