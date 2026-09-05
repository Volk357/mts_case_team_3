"""Static acceptance checks for the backend container contract."""

import unittest
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
DOCKERFILE = REPOSITORY / "apps" / "api" / "Dockerfile"
DOCKERIGNORE = REPOSITORY / ".dockerignore"
ENTRYPOINT = REPOSITORY / "apps" / "api" / "scripts" / "container_entrypoint.py"


class BackendContainerTests(unittest.TestCase):
    def test_image_installs_both_application_components_from_locks(self) -> None:
        dockerfile = DOCKERFILE.read_text(encoding="utf-8")

        self.assertIn(
            "FROM python:${PYTHON_VERSION}-slim-bookworm AS builder", dockerfile
        )
        self.assertIn("apps/api/requirements.lock", dockerfile)
        self.assertIn("requirements-core.lock", dockerfile)
        self.assertIn(
            "pip install --no-deps --no-build-isolation /build/apps/api /build/core",
            dockerfile,
        )
        self.assertIn("docreview version", dockerfile)
        self.assertIn("/build/mock", dockerfile)
        self.assertIn("docreview-mock version", dockerfile)

    def test_runtime_is_non_root_and_exposes_both_roles(self) -> None:
        dockerfile = DOCKERFILE.read_text(encoding="utf-8")
        entrypoint = ENTRYPOINT.read_text(encoding="utf-8")

        self.assertIn("USER docreview", dockerfile)
        self.assertIn("HEALTHCHECK", dockerfile)
        self.assertIn("DOCREVIEW_CONTAINER_ROLE=api", dockerfile)
        self.assertIn('"docreview_api.workers.review_worker"', entrypoint)
        self.assertIn('"api"', entrypoint)
        self.assertIn('"migrate"', entrypoint)
        self.assertNotIn("model-config.yaml /app", dockerfile)

    def test_build_context_excludes_runtime_data_and_model_config(self) -> None:
        ignored = set(DOCKERIGNORE.read_text(encoding="utf-8").splitlines())

        self.assertIn("data", ignored)
        self.assertIn("model-config.yaml", ignored)
        self.assertIn("**/.venv", ignored)
        self.assertIn("**/node_modules", ignored)


if __name__ == "__main__":
    unittest.main()
