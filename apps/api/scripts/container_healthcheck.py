"""Dependency-free health probe shared by the API and worker containers."""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.request import urlopen


def _api_is_ready() -> bool:
    url = os.environ.get("DOCREVIEW_CONTAINER_HEALTH_URL", "http://127.0.0.1:8000/api/health")
    try:
        with urlopen(url, timeout=3) as response:
            payload = json.load(response)
    except (OSError, ValueError, TypeError):
        return False
    return response.status == 200 and payload.get("status") == "ok"


def _worker_is_ready() -> bool:
    path = Path(os.environ.get("DOCREVIEW_WORKER_HEARTBEAT_PATH", "/app/data/worker-heartbeat"))
    try:
        stamp = datetime.fromisoformat(path.read_text(encoding="utf-8").strip())
        poll_interval = float(os.environ.get("DOCREVIEW_WORKER_POLL_INTERVAL_SECONDS", "1"))
        tolerance_factor = float(os.environ.get("DOCREVIEW_WORKER_HEARTBEAT_TOLERANCE", "3"))
    except (OSError, ValueError):
        return False
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    tolerance = timedelta(seconds=max(0.1, min(poll_interval, 5.0)) * tolerance_factor)
    return datetime.now(UTC) - stamp <= tolerance


def main() -> int:
    role = os.environ.get("DOCREVIEW_CONTAINER_ROLE", "api")
    if role == "api":
        healthy = _api_is_ready()
    elif role == "worker":
        healthy = _worker_is_ready()
    else:
        healthy = False
    return 0 if healthy else 1


if __name__ == "__main__":
    sys.exit(main())
