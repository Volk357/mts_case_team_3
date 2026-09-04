"""Generate the checked-in OpenAPI contract from the application factory."""

from __future__ import annotations

import json
from pathlib import Path

from docreview_api.config import Settings
from docreview_api.main import create_app

OUTPUT_PATH = Path(__file__).resolve().parents[1] / "openapi.json"


def generate() -> Path:
    """Write a deterministic, reviewable OpenAPI snapshot."""

    schema = create_app(Settings(environment="test", _env_file=None)).openapi()
    OUTPUT_PATH.write_text(
        json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return OUTPUT_PATH


if __name__ == "__main__":
    print(generate())
