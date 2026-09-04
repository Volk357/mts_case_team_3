from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from docreview_api.config import Settings
from docreview_api.main import create_app

OPENAPI_PATH = Path(__file__).resolve().parents[1] / "openapi.json"


def test_generated_openapi_matches_application() -> None:
    checked_in: dict[str, Any] = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))
    generated = create_app(Settings(environment="test", _env_file=None)).openapi()

    assert checked_in == generated
    assert checked_in["openapi"].startswith("3.")
    assert set(checked_in["paths"]) >= {
        "/api/documents",
        "/api/documents/{document_id}",
        "/api/review-packs",
        "/api/reviews",
        "/api/reviews/{review_id}",
        "/api/reviews/{review_id}/findings",
        "/api/findings/{finding_id}/feedback",
    }
