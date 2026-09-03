"""Safe test/demo scenario selection for the Mock Analysis Core."""

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from importlib.resources import files

from docreview_mock.failure_fixtures import build_failure_manifest, build_failure_payloads
from docreview_mock.success_fixtures import build_success_scenarios

PROFILE_ENVIRONMENT_VARIABLE = "DOCREVIEW_MOCK_PROFILE"
SCENARIO_ENVIRONMENT_VARIABLE = "DOCREVIEW_MOCK_SCENARIO"
DELAY_ENVIRONMENT_VARIABLE = "DOCREVIEW_MOCK_DELAY_MS"
ALLOWED_PROFILES = frozenset({"test", "demo"})
MAX_DELAY_MS = 30_000


class ScenarioConfigurationError(ValueError):
    """Raised when mock-only configuration is unsafe or invalid."""


@dataclass(frozen=True)
class ScenarioConfiguration:
    """Resolved mock behavior for one CLI invocation."""

    name: str
    delay_ms: int


@dataclass(frozen=True)
class ScenarioResult:
    """Process behavior and optional stdout returned by one scenario."""

    exit_code: int
    stdout: str | None
    stderr: str


def available_scenarios() -> frozenset[str]:
    """Return every stable scenario name exposed by the mock."""

    success = {filename.removesuffix(".json") for filename in build_success_scenarios()}
    return frozenset(success | build_failure_manifest().keys())


def _default_delay_ms(scenario: str) -> int:
    failure = build_failure_manifest().get(scenario)
    return 0 if failure is None else int(failure["delay_ms"])


def _load_profile(profile: str) -> dict[str, object]:
    resource = files("docreview_mock").joinpath("profiles", f"{profile}.json")
    try:
        profile_data = json.loads(resource.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:  # pragma: no cover - packaging guard
        raise ScenarioConfigurationError(f"cannot load mock profile: {profile}") from error
    if not isinstance(profile_data, dict):  # pragma: no cover - checked-in profile guard
        raise ScenarioConfigurationError(f"invalid mock profile: {profile}")
    return profile_data


def _parse_delay(value: object) -> int:
    try:
        delay_ms = int(str(value))
    except ValueError as error:
        raise ScenarioConfigurationError("mock delay must be an integer") from error
    if not 0 <= delay_ms <= MAX_DELAY_MS:
        raise ScenarioConfigurationError(
            f"mock delay must be between 0 and {MAX_DELAY_MS} milliseconds"
        )
    return delay_ms


def load_scenario_configuration(
    environ: Mapping[str, str] | None = None,
) -> ScenarioConfiguration | None:
    """Load mock behavior only when an explicit test/demo profile is active."""

    environment = os.environ if environ is None else environ
    profile = environment.get(PROFILE_ENVIRONMENT_VARIABLE)
    has_overrides = any(
        name in environment for name in (SCENARIO_ENVIRONMENT_VARIABLE, DELAY_ENVIRONMENT_VARIABLE)
    )
    if profile is None:
        if has_overrides:
            raise ScenarioConfigurationError(
                "mock scenario overrides require DOCREVIEW_MOCK_PROFILE=test or demo"
            )
        return None
    if profile not in ALLOWED_PROFILES:
        raise ScenarioConfigurationError("mock profile must be test or demo")

    profile_data = _load_profile(profile)
    scenario = environment.get(SCENARIO_ENVIRONMENT_VARIABLE, str(profile_data["scenario"]))
    if scenario not in available_scenarios():
        raise ScenarioConfigurationError(f"unknown mock scenario: {scenario}")
    delay = environment.get(
        DELAY_ENVIRONMENT_VARIABLE,
        profile_data.get("delay_ms", _default_delay_ms(scenario)),
    )
    return ScenarioConfiguration(name=scenario, delay_ms=_parse_delay(delay))


def resolve_scenario(name: str) -> ScenarioResult:
    """Resolve one selected scenario without reading application configuration."""

    success_payloads = build_success_scenarios()
    success_filename = f"{name}.json"
    if success_filename in success_payloads:
        return ScenarioResult(
            exit_code=0,
            stdout=json.dumps(success_payloads[success_filename], ensure_ascii=False),
            stderr=f"mock: completed scenario {name}",
        )

    manifest = build_failure_manifest()[name]
    result_file = manifest["result_file"]
    stdout: str | None = None
    if result_file is not None:
        payload = build_failure_payloads()[result_file]
        stdout = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return ScenarioResult(
        exit_code=int(manifest["exit_code"]),
        stdout=stdout,
        stderr=str(manifest["stderr"]),
    )
