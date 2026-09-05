"""Acceptance checks for complete mock/real Compose orchestration."""

import unittest
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
COMPOSE = REPOSITORY / "compose.yaml"
WORKER = (
    REPOSITORY
    / "apps"
    / "api"
    / "src"
    / "docreview_api"
    / "workers"
    / "review_worker.py"
)


class ComposeOrchestrationTests(unittest.TestCase):
    def test_complete_application_services_and_health_dependencies(self) -> None:
        compose = COMPOSE.read_text(encoding="utf-8")

        for service in ("postgres", "api", "worker", "frontend"):
            self.assertIn(f"  {service}:\n", compose)
        self.assertIn("condition: service_healthy", compose)
        self.assertIn("condition: service_completed_successfully", compose)
        self.assertIn("restart: unless-stopped", compose)
        self.assertIn("resources:", compose)

    def test_mock_and_real_workers_are_mutually_selectable_profiles(self) -> None:
        compose = COMPOSE.read_text(encoding="utf-8")

        self.assertIn('profiles: ["mock"]', compose)
        self.assertIn('profiles: ["real"]', compose)
        self.assertIn("DOCREVIEW_ANALYSIS_EXECUTABLE: docreview-mock", compose)
        self.assertIn("DOCREVIEW_ANALYSIS_EXECUTABLE: docreview", compose)
        self.assertIn("model-preflight:", compose)

    def test_mock_controls_cross_the_sanitized_process_boundary_explicitly(
        self,
    ) -> None:
        worker = WORKER.read_text(encoding="utf-8")

        self.assertIn("MOCK_PROCESS_ENVIRONMENT_KEYS", worker)
        self.assertIn("analysis_process_environment", worker)
        self.assertIn("environment=analysis_process_environment", worker)

    def test_postgresql_queue_does_not_add_redis(self) -> None:
        compose = COMPOSE.read_text(encoding="utf-8")

        self.assertNotIn("  redis:", compose)


if __name__ == "__main__":
    unittest.main()
