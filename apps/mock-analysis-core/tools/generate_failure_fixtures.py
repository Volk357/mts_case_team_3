"""Regenerate checked-in failure fixtures and their behavior manifest."""

import json
from pathlib import Path
from typing import Any

from docreview_mock.failure_fixtures import build_failure_manifest, build_failure_payloads

FIXTURES_DIRECTORY = Path(__file__).resolve().parents[1] / "fixtures" / "failure"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> None:
    FIXTURES_DIRECTORY.mkdir(parents=True, exist_ok=True)
    _write_json(FIXTURES_DIRECTORY / "manifest.json", build_failure_manifest())
    for filename, payload in build_failure_payloads().items():
        destination = FIXTURES_DIRECTORY / filename
        if isinstance(payload, str):
            destination.write_text(payload + "\n", encoding="utf-8", newline="\n")
        else:
            _write_json(destination, payload)


if __name__ == "__main__":
    main()
