"""Small exec-only entrypoint for the immutable backend image."""

from __future__ import annotations

import os
import sys

COMMANDS = {
    "api": (
        "python",
        "-m",
        "uvicorn",
        "docreview_api.main:app",
        "--host",
        "0.0.0.0",
        "--port",
        "8000",
    ),
    "worker": ("python", "-m", "docreview_api.workers.review_worker"),
    "migrate": (
        "python",
        "-m",
        "alembic",
        "-c",
        "/app/apps/api/alembic.ini",
        "upgrade",
        "head",
    ),
    "seed-demo": ("python", "/app/bin/seed_demo.py"),
    "storage-check": ("python", "/app/bin/verify_container_storage.py"),
    "model-preflight": ("python", "/app/bin/model_preflight.py"),
}


def main(arguments: list[str] | None = None) -> int:
    requested = list(sys.argv[1:] if arguments is None else arguments)
    if not requested:
        requested = ["api"]
    command = [*COMMANDS.get(requested[0], tuple(requested))]
    os.execvp(command[0], command)
    return 127  # pragma: no cover - os.execvp replaces the process or raises


if __name__ == "__main__":
    sys.exit(main())
