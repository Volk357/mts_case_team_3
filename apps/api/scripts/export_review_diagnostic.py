"""Export a review's private integration diagnostic without document content."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from uuid import UUID

from docreview_api.config import load_settings
from docreview_api.db.models import ReviewJobModel
from docreview_api.db.session import create_database_engine, create_session_factory
from docreview_api.services.review_job_executor import DIAGNOSTIC_ARTIFACT_NAME
from docreview_api.services.run_workspace import RunWorkspaceManager


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export command, exit code, stderr and contract errors for one review."
    )
    parser.add_argument("review_id", type=UUID)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def _read_execution_report(runs_dir: Path, run_id: str) -> dict[str, Any] | None:
    try:
        workspace = RunWorkspaceManager(runs_dir).open(run_id)
        path = workspace.artifacts_dir / DIAGNOSTIC_ARTIFACT_NAME
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def main() -> int:
    arguments = _arguments()
    output = arguments.output.resolve()
    if output.exists() and not arguments.force:
        raise SystemExit(f"Output already exists: {output}. Pass --force to replace it.")

    settings = load_settings()
    engine = create_database_engine(settings.database_url)
    sessions = create_session_factory(engine)
    try:
        with sessions() as session:
            job = session.get(ReviewJobModel, arguments.review_id)
            if job is None or job.company_id != settings.default_company_id:
                raise SystemExit("Review was not found for the configured company.")
            report = {
                "format_version": "1.0",
                "review": {
                    "review_id": str(job.id),
                    "run_id": job.run_id,
                    "status": job.status.value,
                    "error_code": job.error_code,
                    "diagnostic_message": job.diagnostic_message,
                },
                "execution": _read_execution_report(settings.runs_dir, job.run_id),
            }
    finally:
        engine.dispose()

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
