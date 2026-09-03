"""Regenerate checked-in success JSON fixtures."""

import json
from pathlib import Path

from docreview_mock.success_fixtures import build_success_scenarios

FIXTURES_DIRECTORY = Path(__file__).resolve().parents[1] / "fixtures" / "success"


def main() -> None:
    FIXTURES_DIRECTORY.mkdir(parents=True, exist_ok=True)
    for filename, payload in build_success_scenarios().items():
        destination = FIXTURES_DIRECTORY / filename
        destination.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )


if __name__ == "__main__":
    main()
