import json
from pathlib import Path

import pytest

from docreview_mock import cli
from docreview_mock.scenario import (
    ScenarioConfigurationError,
    available_scenarios,
    load_scenario_configuration,
    resolve_scenario,
)


def test_all_success_and_failure_scenarios_are_selectable() -> None:
    assert available_scenarios() == {
        "empty",
        "standard-12",
        "maximum-20",
        "document-parse-error",
        "review-pack-not-found",
        "model-unavailable",
        "invalid-json",
        "incompatible-schema-version",
        "timeout",
        "crash",
        "missing-result-after-success",
    }


def test_overrides_are_rejected_without_explicit_safe_profile() -> None:
    with pytest.raises(ScenarioConfigurationError, match="require"):
        load_scenario_configuration({"DOCREVIEW_MOCK_SCENARIO": "standard-12"})


@pytest.mark.parametrize("profile", ["development", "production", "staging"])
def test_non_test_profiles_are_rejected(profile: str) -> None:
    with pytest.raises(ScenarioConfigurationError, match="test or demo"):
        load_scenario_configuration({"DOCREVIEW_MOCK_PROFILE": profile})


def test_demo_profile_has_a_predictable_progress_delay() -> None:
    configuration = load_scenario_configuration({"DOCREVIEW_MOCK_PROFILE": "demo"})

    assert configuration is not None
    assert configuration.name == "standard-12"
    assert configuration.delay_ms == 1200


def test_timeout_uses_manifest_delay_unless_test_profile_overrides_it() -> None:
    default = load_scenario_configuration(
        {
            "DOCREVIEW_MOCK_PROFILE": "test",
            "DOCREVIEW_MOCK_SCENARIO": "timeout",
        }
    )
    overridden = load_scenario_configuration(
        {
            "DOCREVIEW_MOCK_PROFILE": "test",
            "DOCREVIEW_MOCK_SCENARIO": "timeout",
            "DOCREVIEW_MOCK_DELAY_MS": "25",
        }
    )

    assert default is not None and default.delay_ms == 1500
    assert overridden is not None and overridden.delay_ms == 25


@pytest.mark.parametrize("delay", ["slow", "-1", "30001"])
def test_invalid_delay_is_rejected(delay: str) -> None:
    with pytest.raises(ScenarioConfigurationError, match="delay"):
        load_scenario_configuration(
            {
                "DOCREVIEW_MOCK_PROFILE": "test",
                "DOCREVIEW_MOCK_DELAY_MS": delay,
            }
        )


def test_selected_success_scenario_binds_invocation_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = tmp_path / "актуальный-документ.pdf"
    document.write_bytes(b"document")
    review_pack = tmp_path / "company-pack"
    review_pack.mkdir()
    output = tmp_path / "result.json"
    delays: list[float] = []
    monkeypatch.setenv("DOCREVIEW_MOCK_PROFILE", "demo")
    monkeypatch.setenv("DOCREVIEW_MOCK_DELAY_MS", "75")
    monkeypatch.setattr(cli.time, "sleep", delays.append)

    exit_code = cli.main(
        [
            "analyze",
            "--file",
            str(document),
            "--pack",
            str(review_pack),
            "--run-id",
            "current-run",
            "--output",
            str(output),
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert delays == [0.075]
    assert payload["run_id"] == "current-run"
    assert payload["document"]["filename"] == document.name
    assert payload["review_pack"]["id"] == "company-pack"
    assert payload["summary"]["returned_findings"] == 12
    assert output.read_text(encoding="utf-8") == captured.out
    assert "standard-12" in captured.err


def test_selected_failure_controls_stdout_stderr_and_exit_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = tmp_path / "document.pdf"
    document.write_bytes(b"document")
    review_pack = tmp_path / "pack"
    review_pack.mkdir()
    monkeypatch.setenv("DOCREVIEW_MOCK_PROFILE", "test")
    monkeypatch.setenv("DOCREVIEW_MOCK_SCENARIO", "model-unavailable")

    exit_code = cli.main(
        [
            "analyze",
            "--file",
            str(document),
            "--pack",
            str(review_pack),
            "--run-id",
            "failed-run",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 5
    assert json.loads(captured.out)["run_id"] == "failed-run"
    assert "model endpoint is unavailable" in captured.err


def test_no_result_scenario_does_not_create_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = tmp_path / "document.pdf"
    document.write_bytes(b"document")
    review_pack = tmp_path / "pack"
    review_pack.mkdir()
    output = tmp_path / "result.json"
    monkeypatch.setenv("DOCREVIEW_MOCK_PROFILE", "test")
    monkeypatch.setenv("DOCREVIEW_MOCK_SCENARIO", "missing-result-after-success")

    exit_code = cli.main(
        [
            "analyze",
            "--file",
            str(document),
            "--pack",
            str(review_pack),
            "--run-id",
            "missing-result",
            "--output",
            str(output),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.out == ""
    assert not output.exists()
    assert "without result" in captured.err


def test_failure_scenario_resolver_preserves_intentionally_invalid_json() -> None:
    scenario = resolve_scenario("invalid-json")

    assert scenario.exit_code == 6
    assert scenario.stdout is not None
    with pytest.raises(json.JSONDecodeError):
        json.loads(scenario.stdout)
