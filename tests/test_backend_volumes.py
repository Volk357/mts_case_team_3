"""Acceptance checks for persistent backend storage mounts."""

import unittest
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
COMPOSE = REPOSITORY / "compose.yaml"
DOCKERFILE = REPOSITORY / "apps" / "api" / "Dockerfile"
STORAGE_CHECK = REPOSITORY / "apps" / "api" / "scripts" / "verify_container_storage.py"


class BackendVolumeTests(unittest.TestCase):
    def test_runtime_data_has_separate_named_volumes(self) -> None:
        compose = COMPOSE.read_text(encoding="utf-8")

        for source, target in (
            ("documents_data", "/app/data/documents"),
            ("runs_data", "/app/data/runs"),
            ("artifacts_data", "/app/data/artifacts"),
            ("runtime_state", "/app/data/state"),
        ):
            self.assertIn(f"source: {source}", compose)
            self.assertIn(f"target: {target}", compose)

    def test_review_packs_are_a_read_only_bind_mount(self) -> None:
        compose = COMPOSE.read_text(encoding="utf-8")

        self.assertIn("source: ./review-packs", compose)
        self.assertIn("target: /app/review-packs", compose)
        self.assertIn("read_only: true", compose)

    def test_storage_check_runs_as_the_non_root_image_user(self) -> None:
        compose = COMPOSE.read_text(encoding="utf-8")
        dockerfile = DOCKERFILE.read_text(encoding="utf-8")
        check = STORAGE_CHECK.read_text(encoding="utf-8")

        self.assertIn('command: ["storage-check"]', compose)
        self.assertIn("USER docreview", dockerfile)
        self.assertNotIn("user: root", compose)
        self.assertIn("stat.st_uid != os.getuid()", check)
        self.assertIn("Review Packs directory is writable", check)


if __name__ == "__main__":
    unittest.main()
